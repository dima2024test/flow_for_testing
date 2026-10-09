from flowlib import Flow, R, D
from common import log_fault, PFX


def contact_before_save():
    f = Flow("RTF_Contact_Before_Save_Defaults", "RTF Contact Before Save Defaults", "rtf",
             "Before-save on Contact create: copies phone/mailing address from the Account when blank, defaults LeadSource, and notes "
             "possible duplicate e-mails in Description (only if Description is empty).")
    f.var("varDuplicateCount", "Number", scale=0, default=0)
    f.formula("fxDuplicateNote", "String", "'Possible duplicate: ' & TEXT({!varDuplicateCount}) & ' other contact(s) share this email.'")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Get_Account")], "Dec_Lead_Source", "No Account")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], "Dec_Phone_Missing", first=True)
    f.decision("Dec_Phone_Missing", [("Phone_Missing", [("$Record.Phone", "IsNull", True), ("Get_Account.Phone", "IsNull", False)], "Asg_Copy_Phone")],
               "Dec_Address_Missing", "Phone Present")
    f.assign("Asg_Copy_Phone", [("$Record.Phone", "Assign", R("Get_Account.Phone"))], "Dec_Address_Missing")
    f.decision("Dec_Address_Missing", [("Address_Missing", [("$Record.MailingCity", "IsNull", True), ("Get_Account.BillingCity", "IsNull", False)], "Asg_Copy_Address")],
               "Dec_Lead_Source", "Address Present")
    f.assign("Asg_Copy_Address", [("$Record.MailingStreet", "Assign", R("Get_Account.BillingStreet")), ("$Record.MailingCity", "Assign", R("Get_Account.BillingCity")),
                                  ("$Record.MailingPostalCode", "Assign", R("Get_Account.BillingPostalCode")),
                                  ("$Record.MailingCountry", "Assign", R("Get_Account.BillingCountry"))], "Dec_Lead_Source")
    f.decision("Dec_Lead_Source", [("Source_Missing", [("$Record.LeadSource", "IsNull", True)], "Asg_Default_Source")], "Dec_Has_Email", "Source Set")
    f.assign("Asg_Default_Source", [("$Record.LeadSource", "Assign", "Other")], "Dec_Has_Email")
    f.decision("Dec_Has_Email", [("Has_Email", [("$Record.Email", "IsNull", False), ("$Record.Description", "IsNull", True)], "Get_Same_Email_Contacts")], None, "Skip Check")
    f.get("Get_Same_Email_Contacts", "Contact", [("Email", "EqualTo", R("$Record.Email"))], "Loop_Same_Email")
    f.loop("Loop_Same_Email", "Get_Same_Email_Contacts", "Asg_Count_Duplicate", "Dec_Duplicate_Found")
    f.assign("Asg_Count_Duplicate", [("varDuplicateCount", "Add", 1)], "Loop_Same_Email")
    f.decision("Dec_Duplicate_Found", [("Duplicate", [("varDuplicateCount", "GreaterThan", 0)], "Asg_Duplicate_Note")], None, "Unique")
    f.assign("Asg_Duplicate_Note", [("$Record.Description", "Assign", R("fxDuplicateNote"))])
    f.start("Dec_Has_Account", obj="Contact", trigger="RecordBeforeSave", record_trigger="Create")
    return f


def task_completed():
    f = Flow("RTF_Task_Completed_Followup", "RTF Task Completed Followup", "rtf",
             "After-save when a '[Flow Demo]' Task is completed: for Opportunity tasks creates the next-step Task if the deal is open; "
             "for Case tasks marks the case Working when no other open demo tasks remain.")
    f.var("varOpenSiblings", "Number", scale=0, default=0)
    f.formula("fxWhatPrefix", "String", "LEFT({!$Record.WhatId}, 3)")
    f.formula("fxDueDate", "Date", "TODAY() + 3")
    f.tt("ttNote", "Previous step '{!$Record.Subject}' completed by {!$User.Username} on {!$Flow.CurrentDate}.")
    f.decision("Dec_Related_Type", [
        ("Opportunity_Task", [("fxWhatPrefix", "EqualTo", "006")], "Get_Opportunity"),
        ("Case_Task", [("fxWhatPrefix", "EqualTo", "500")], "Get_Sibling_Tasks")], None, "Other")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("$Record.WhatId"))], "Dec_Opp_Open", "Log_Fault", first=True)
    f.decision("Dec_Opp_Open", [("Open", [("Get_Opportunity", "IsNull", False), ("Get_Opportunity.IsClosed", "EqualTo", False)], "Get_Existing_Next_Step")],
               None, "Closed")
    f.get("Get_Existing_Next_Step", "Task", [("WhatId", "EqualTo", R("$Record.WhatId")), ("IsClosed", "EqualTo", False),
                                             ("Subject", "EqualTo", PFX + "Next step after completed task")],
          "Dec_Next_Step_Exists", "Log_Fault", first=True)
    f.decision("Dec_Next_Step_Exists", [("Exists", [("Get_Existing_Next_Step", "IsNull", False)], None)], "Create_Next_Step_Task", "None Open")
    f.create("Create_Next_Step_Task", "Task", {"Subject": PFX + "Next step after completed task", "WhatId": R("$Record.WhatId"),
                                               "OwnerId": R("Get_Opportunity.OwnerId"), "Description": R("ttNote"), "ActivityDate": R("fxDueDate"),
                                               "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.get("Get_Sibling_Tasks", "Task", [("WhatId", "EqualTo", R("$Record.WhatId")), ("Subject", "StartsWith", PFX), ("Id", "NotEqualTo", R("$Record.Id"))],
          "Loop_Siblings", "Log_Fault")
    f.loop("Loop_Siblings", "Get_Sibling_Tasks", "Dec_Sibling_Open", "Dec_All_Done")
    f.decision("Dec_Sibling_Open", [("Sibling_Open", [("Loop_Siblings.IsClosed", "EqualTo", False)], "Asg_Count_Open")], "Loop_Siblings", "Closed")
    f.assign("Asg_Count_Open", [("varOpenSiblings", "Add", 1)], "Loop_Siblings")
    f.decision("Dec_All_Done", [("All_Done", [("varOpenSiblings", "EqualTo", 0)], "Get_Case")], None, "Still Open")
    f.get("Get_Case", "Case", [("Id", "EqualTo", R("$Record.WhatId"))], "Dec_Case_New", "Log_Fault", first=True)
    f.decision("Dec_Case_New", [("Case_New", [("Get_Case.Status", "EqualTo", "New")], "Update_Case_Working")], None, "Already Progressed")
    f.update("Update_Case_Working", "Case", [("Id", "EqualTo", R("$Record.WhatId"))], {"Status": "Working"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Related_Type", obj="Task", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("IsClosed", "EqualTo", True), ("Subject", "StartsWith", PFX)], changed=True)
    return f


def opp_amount_audit():
    f = Flow("RTF_Opportunity_Amount_Change_Audit", "RTF Opportunity Amount Change Audit", "rtf",
             "After-save on open Opportunity update: compares Amount and Probability with the prior values ($Record__Prior), audits large "
             "changes with a Task + e-mail and flags probability drops. Async path refreshes the pipeline summary.")
    f.var("varLineItemCount", "Number", scale=0, default=0)
    f.var("varPipeline", "Currency", scale=2)
    f.formula("fxPriorAmount", "Currency", "BLANKVALUE({!$Record__Prior.Amount}, 0)", scale=2)
    f.formula("fxNewAmount", "Currency", "BLANKVALUE({!$Record.Amount}, 0)", scale=2)
    f.formula("fxChangePct", "Number", "IF({!fxPriorAmount} = 0, 100, ABS({!fxNewAmount} - {!fxPriorAmount}) / {!fxPriorAmount} * 100)", scale=2)
    f.tt("ttAudit", "Opportunity {!$Record.Name}: amount changed from {!fxPriorAmount} to {!fxNewAmount} ({!fxChangePct}%).\n"
                    "Products on the deal: {!varLineItemCount}. Changed by {!$User.Username}.")
    f.decision("Dec_What_Changed", [
        ("Amount_Changed", [("$Record.Amount", "NotEqualTo", R("$Record__Prior.Amount"))], "Dec_Large_Change"),
        ("Probability_Dropped", [("$Record.Probability", "LessThan", R("$Record__Prior.Probability"))], "Create_Probability_Task")],
        None, "Nothing Relevant")
    f.decision("Dec_Large_Change", [("Large_Change", [("fxChangePct", "GreaterThanOrEqualTo", 50)], "Get_Line_Items")], None, "Small Change")
    f.get("Get_Line_Items", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("$Record.Id"))], "Loop_Line_Items", "Log_Fault")
    f.loop("Loop_Line_Items", "Get_Line_Items", "Asg_Count_Item", "Create_Audit_Task")
    f.assign("Asg_Count_Item", [("varLineItemCount", "Add", 1)], "Loop_Line_Items")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Large amount change", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                           "Description": R("ttAudit"), "Priority": "High", "Status": "Not Started"}, "Send_Audit_Email", "Log_Fault")
    f.email("Send_Audit_Email", R("$User.Email"), PFX + "Large opportunity amount change", R("ttAudit"), None, "Log_Fault")
    f.create("Create_Probability_Task", "Task", {"Subject": PFX + "Probability decreased - review deal", "WhatId": R("$Record.Id"),
                                                 "OwnerId": R("$Record.OwnerId"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Sub_Pipeline_Summary")], None, "No Account")
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("$Record.AccountId"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline"})
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_What_Changed", obj="Opportunity", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("IsClosed", "EqualTo", False), ("Amount", "IsChanged", True), ("Probability", "IsChanged", True)],
            filter_logic="1 AND (2 OR 3)", paths=[{"async": "Dec_Has_Account"}])
    return f


def case_closed():
    f = Flow("RTF_Case_Closed_Followup", "RTF Case Closed Followup", "rtf",
             "After-save when a Case is closed: satisfaction-call Task for the contact owner, account-level check for remaining open cases; "
             "scheduled path 3 days after ClosedDate checks for reopen and contact activity via subflow.")
    f.var("varOpenCaseCount", "Number", scale=0, default=0)
    f.var("varEngagement", "String")
    f.formula("fxDueDate", "Date", "TODAY() + 2")
    f.tt("ttClosed", "Case {!$Record.CaseNumber} '{!$Record.Subject}' was closed. Remaining open cases on the account: {!varOpenCaseCount}.")
    f.decision("Dec_Has_Contact", [("Has_Contact", [("$Record.ContactId", "IsNull", False)], "Get_Contact")], "Dec_Has_Account", "No Contact")
    f.get("Get_Contact", "Contact", [("Id", "EqualTo", R("$Record.ContactId"))], "Create_Satisfaction_Task", "Log_Fault", first=True)
    f.create("Create_Satisfaction_Task", "Task", {"Subject": PFX + "Satisfaction call after case closure", "WhoId": R("$Record.ContactId"),
                                                  "WhatId": R("$Record.Id"), "OwnerId": R("Get_Contact.OwnerId"), "ActivityDate": R("fxDueDate"),
                                                  "Priority": "Normal", "Status": "Not Started"}, "Dec_Has_Account", "Log_Fault")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Get_Open_Account_Cases")], None, "No Account")
    f.get("Get_Open_Account_Cases", "Case", [("AccountId", "EqualTo", R("$Record.AccountId")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCaseCount", "AssignCount", R("Get_Open_Account_Cases"))], "Dec_Account_Clear")
    f.decision("Dec_Account_Clear", [("All_Clear", [("varOpenCaseCount", "EqualTo", 0)], "Create_All_Clear_Task")], None, "Cases Remain")
    f.create("Create_All_Clear_Task", "Task", {"Subject": PFX + "Account has no open cases", "WhatId": R("$Record.AccountId"), "Description": R("ttClosed"),
                                               "Priority": "Low", "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Closure_Email", "Log_Fault")
    f.email("Send_Closure_Email", R("$User.Email"), PFX + "All cases closed for account", R("ttClosed"), None, "Log_Fault")
    # scheduled path
    f.get("Get_Case_Later", "Case", [("Id", "EqualTo", R("$Record.Id"))], "Dec_Reopened", "Log_Fault", first=True)
    f.decision("Dec_Reopened", [("Reopened", [("Get_Case_Later.IsClosed", "EqualTo", False)], "Create_Reopen_Task")], "Dec_Contact_For_Snapshot", "Still Closed")
    f.create("Create_Reopen_Task", "Task", {"Subject": PFX + "Case reopened within 3 days", "WhatId": R("$Record.Id"),
                                            "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    f.decision("Dec_Contact_For_Snapshot", [("Contact_Present", [("$Record.ContactId", "IsNull", False)], "Sub_Contact_Snapshot")], None, "No Contact")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("$Record.ContactId")}, {"outEngagement": "varEngagement"})
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Has_Contact", obj="Case", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("IsClosed", "EqualTo", True)], changed=True,
            paths=[dict(name="Three_Days_After_Close", label="3 Days After Close", target="Get_Case_Later", num=3, unit="Days", field="ClosedDate")])
    return f


def owner_cascade():
    f = Flow("RTF_Account_Owner_Change_Cascade", "RTF Account Owner Change Cascade", "rtf",
             "After-save on Account update when OwnerId changes ($Record__Prior): moves the prior owner's open Opportunities and "
             "open account Tasks to the new owner in two bulk updates, then leaves a handover Task and e-mail.")
    f.var("varOpp", "SObject", obj="Opportunity")
    f.var("colOppsToUpdate", "SObject", coll=True, obj="Opportunity")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varMovedOpps", "Number", scale=0, default=0)
    f.var("varMovedTasks", "Number", scale=0, default=0)
    f.tt("ttSummary", "Account {!$Record.Name} changed owner. Moved to the new owner: {!varMovedOpps} open opportunity(ies), {!varMovedTasks} open task(s).")
    f.decision("Dec_Owner_Changed", [("Owner_Changed", [("$Record.OwnerId", "NotEqualTo", R("$Record__Prior.OwnerId"))], "Get_Open_Opportunities")], None, "Same Owner")
    f.get("Get_Open_Opportunities", "Opportunity", [("AccountId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                                    ("OwnerId", "EqualTo", R("$Record__Prior.OwnerId"))], "Loop_Opportunities", "Log_Fault")
    f.loop("Loop_Opportunities", "Get_Open_Opportunities", "Asg_Opp_Owner", "Dec_Any_Opps", var="varOpp")
    f.assign("Asg_Opp_Owner", [("varOpp.OwnerId", "Assign", R("$Record.OwnerId")), ("colOppsToUpdate", "Add", R("varOpp")), ("varMovedOpps", "Add", 1)], "Loop_Opportunities")
    f.decision("Dec_Any_Opps", [("Has_Opps", [("varMovedOpps", "GreaterThan", 0)], "Update_Opportunities")], "Get_Open_Tasks", "None")
    f.update("Update_Opportunities", input_ref="colOppsToUpdate", nxt="Get_Open_Tasks", fault="Log_Fault")
    f.get("Get_Open_Tasks", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                     ("OwnerId", "EqualTo", R("$Record__Prior.OwnerId"))], "Loop_Tasks", "Log_Fault")
    f.loop("Loop_Tasks", "Get_Open_Tasks", "Asg_Task_Owner", "Dec_Any_Tasks", var="varTask")
    f.assign("Asg_Task_Owner", [("varTask.OwnerId", "Assign", R("$Record.OwnerId")), ("colTasksToUpdate", "Add", R("varTask")), ("varMovedTasks", "Add", 1)], "Loop_Tasks")
    f.decision("Dec_Any_Tasks", [("Has_Tasks", [("varMovedTasks", "GreaterThan", 0)], "Update_Tasks")], "Create_Handover_Task", "None")
    f.update("Update_Tasks", input_ref="colTasksToUpdate", nxt="Create_Handover_Task", fault="Log_Fault")
    f.create("Create_Handover_Task", "Task", {"Subject": PFX + "Account handed over to you", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                              "Description": R("ttSummary"), "Priority": "Normal", "Status": "Not Started"}, "Send_Handover_Email", "Log_Fault")
    f.email("Send_Handover_Email", R("$User.Email"), PFX + "Account owner changed", R("ttSummary"), None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Owner_Changed", obj="Account", trigger="RecordAfterSave", record_trigger="Update")
    return f


ALL = [contact_before_save, task_completed, opp_amount_audit, case_closed, owner_cascade]

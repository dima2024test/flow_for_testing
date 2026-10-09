from flowlib import Flow, R, D
from common import log_fault, PFX


def account_create():
    f = Flow("RTF_Account_After_Create_Setup", "RTF Account After Create Setup", "rtf",
             "After-save on Account create: segment-specific setup (Task / starter Opportunity), duplicate-name check with alert, "
             "contact normalization subflow; scheduled path +1 day runs health scoring subflow.")
    f.var("varDuplicateCount", "Number", scale=0, default=0)
    f.var("varDuplicateList", "String", default="")
    f.var("varHealthScore", "Number", scale=0)
    f.var("varHealthRating", "String")
    f.var("varUpdatedContacts", "Number", scale=0)
    f.var("varSegment", "String")
    f.formula("fxOppName", "String", f"LEFT('{PFX}' & {{!$Record.Name}} & ' - First Deal', 120)")
    f.formula("fxCloseDate", "Date", "TODAY() + 30")
    f.formula("fxDueDate", "Date", "TODAY() + 2")
    f.tt("ttDuplicateBody", "Account {!$Record.Name} ({!$Record.Id}) was created, but {!varDuplicateCount} account(s) with the same name already exist:\n{!varDuplicateList}")
    f.decision("Dec_Account_Type", [
        ("Customer", [("$Record.Type", "Contains", "Customer")], "Create_Welcome_Task"),
        ("Prospect", [("$Record.Type", "EqualTo", "Prospect")], "Create_Starter_Opportunity")],
        "Asg_Default_Segment", "Other")
    f.create("Create_Welcome_Task", "Task", {"Subject": PFX + "Welcome call for new customer", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                             "ActivityDate": R("fxDueDate"), "Priority": "High", "Status": "Not Started"},
             "Get_Similar_Accounts", "Log_Fault")
    f.create("Create_Starter_Opportunity", "Opportunity", {"Name": R("fxOppName"), "AccountId": R("$Record.Id"), "StageName": "Prospecting",
                                                           "CloseDate": R("fxCloseDate"), "OwnerId": R("$Record.OwnerId")},
             "Get_Similar_Accounts", "Log_Fault")
    f.assign("Asg_Default_Segment", [("varSegment", "Assign", "Unclassified")], "Get_Similar_Accounts")
    f.get("Get_Similar_Accounts", "Account", [("Name", "EqualTo", R("$Record.Name")), ("Id", "NotEqualTo", R("$Record.Id"))],
          "Asg_Duplicate_Count", "Log_Fault")
    f.assign("Asg_Duplicate_Count", [("varDuplicateCount", "AssignCount", R("Get_Similar_Accounts"))], "Dec_Has_Duplicates")
    f.decision("Dec_Has_Duplicates", [("Duplicates_Found", [("varDuplicateCount", "GreaterThan", 0)], "Loop_Duplicates")],
               "Sub_Normalize_Contacts", "No Duplicates")
    f.loop("Loop_Duplicates", "Get_Similar_Accounts", "Asg_Collect_Duplicate", "Create_Duplicate_Review_Task")
    f.assign("Asg_Collect_Duplicate", [("varDuplicateList", "Add", R("Loop_Duplicates.Id")), ("varDuplicateList", "Add", "; ")], "Loop_Duplicates")
    f.create("Create_Duplicate_Review_Task", "Task", {"Subject": PFX + "Review possible duplicate account", "WhatId": R("$Record.Id"),
                                                      "Description": R("ttDuplicateBody"), "OwnerId": R("$Record.OwnerId"),
                                                      "Priority": "Normal", "Status": "Not Started"},
             "Send_Duplicate_Alert", "Log_Fault")
    f.email("Send_Duplicate_Alert", R("$User.Email"), PFX + "Possible duplicate account", R("ttDuplicateBody"), "Sub_Normalize_Contacts", "Sub_Normalize_Contacts")
    f.subflow("Sub_Normalize_Contacts", "AUT_Contact_Data_Normalizer", {"inAccountId": R("$Record.Id")}, {"outUpdatedCount": "varUpdatedContacts"})
    # scheduled path (+1 day after CreatedDate)
    f.subflow("Sub_Health_Score", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.Id")},
              {"outScore": "varHealthScore", "outRating": "varHealthRating"}, "Dec_Score_Low")
    f.decision("Dec_Score_Low", [("Low_Score", [("varHealthScore", "LessThan", 40)], "Create_Nurture_Task")], None, "Healthy")
    f.create("Create_Nurture_Task", "Task", {"Subject": PFX + "Nurture low-health account", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                             "ActivityDate": R("fxDueDate"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Account_Type", obj="Account", trigger="RecordAfterSave", record_trigger="Create",
            paths=[dict(name="One_Day_After_Creation", label="1 Day After Creation", target="Sub_Health_Score", num=1, unit="Days", field="CreatedDate")])
    return f


def opp_closed():
    f = Flow("RTF_Opportunity_Closed_Processing", "RTF Opportunity Closed Processing", "rtf",
             "After-save when an Opportunity becomes closed. Won: promote Account type, sum line-item quantity, onboarding Task + e-mail. "
             "Lost: loss-review Task and close open demo Tasks. Scheduled path CloseDate+7 days recalculates Account health.")
    f.var("varTotalQuantity", "Number", scale=2, default=0)
    f.var("varLineItem", "SObject", obj="OpportunityLineItem")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToClose", "SObject", coll=True, obj="Task")
    f.var("varHealthScore", "Number", scale=0)
    f.formula("fxQuantity", "Number", "BLANKVALUE({!varLineItem.Quantity}, 0)", scale=2)
    f.formula("fxDueDate", "Date", "TODAY() + 5")
    f.tt("ttWinBody", "Opportunity {!$Record.Name} was won.\nAmount: {!$Record.Amount}\nTotal product quantity: {!varTotalQuantity}")
    f.decision("Dec_Won_Or_Lost", [("Won", [("$Record.IsWon", "EqualTo", True)], "Get_Account")], "Create_Loss_Review_Task", "Lost")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], "Dec_Promote_Account", "Log_Fault", first=True)
    f.decision("Dec_Promote_Account", [("Needs_Promotion", [("Get_Account", "IsNull", False), ("Get_Account.Type", "NotEqualTo", "Customer - Direct")], "Update_Account_Type")],
               "Get_Line_Items", "Already Customer")
    f.update("Update_Account_Type", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], {"Type": "Customer - Direct"}, "Get_Line_Items", "Log_Fault")
    f.get("Get_Line_Items", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("$Record.Id"))], "Loop_Line_Items", "Log_Fault")
    f.loop("Loop_Line_Items", "Get_Line_Items", "Asg_Sum_Quantity", "Create_Onboarding_Task", var="varLineItem")
    f.assign("Asg_Sum_Quantity", [("varTotalQuantity", "Add", R("fxQuantity"))], "Loop_Line_Items")
    f.create("Create_Onboarding_Task", "Task", {"Subject": PFX + "Kick off customer onboarding", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                                "ActivityDate": R("fxDueDate"), "Description": R("ttWinBody"), "Priority": "High", "Status": "Not Started"},
             "Send_Win_Email", "Log_Fault")
    f.email("Send_Win_Email", R("$User.Email"), PFX + "Opportunity won", R("ttWinBody"), None, "Log_Fault")
    f.create("Create_Loss_Review_Task", "Task", {"Subject": PFX + "Loss review", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                                 "ActivityDate": R("fxDueDate"), "Priority": "Normal", "Status": "Not Started"},
             "Get_Open_Demo_Tasks", "Log_Fault")
    f.get("Get_Open_Demo_Tasks", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                          ("Subject", "StartsWith", PFX), ("Subject", "NotEqualTo", PFX + "Loss review")],
          "Loop_Open_Tasks", "Log_Fault")
    f.loop("Loop_Open_Tasks", "Get_Open_Demo_Tasks", "Asg_Close_Task", "Update_Open_Tasks", var="varTask")
    f.assign("Asg_Close_Task", [("varTask.Status", "Assign", "Completed"), ("colTasksToClose", "Add", R("varTask"))], "Loop_Open_Tasks")
    f.update("Update_Open_Tasks", input_ref="colTasksToClose", fault="Log_Fault")
    f.subflow("Sub_Account_Health", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.AccountId")}, {"outScore": "varHealthScore"})
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Won_Or_Lost", obj="Opportunity", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("IsClosed", "EqualTo", True)], changed=True,
            paths=[dict(name="Seven_Days_After_Close", label="7 Days After Close", target="Sub_Account_Health", num=7, unit="Days", field="CloseDate")])
    return f


def case_before_save():
    f = Flow("RTF_Case_Before_Save_Triage", "RTF Case Before Save Triage", "rtf",
             "Before-save (fast field update) on Case create: derives Priority from Account rating/type, the contact's open cases in "
             "the last 30 days and Origin; defaults Origin to Web.")
    f.var("varAccountRating", "String")
    f.var("varAccountType", "String")
    f.var("varOpenCaseCount", "Number", scale=0, default=0)
    f.formula("fxLast30Days", "DateTime", "NOW() - 30")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Get_Account")], "Dec_Has_Contact", "No Account")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], "Asg_Account_Context", first=True)
    f.assign("Asg_Account_Context", [("varAccountRating", "Assign", R("Get_Account.Rating")), ("varAccountType", "Assign", R("Get_Account.Type"))], "Dec_Has_Contact")
    f.decision("Dec_Has_Contact", [("Has_Contact", [("$Record.ContactId", "IsNull", False)], "Get_Contact_Cases")], "Dec_Priority_Rule", "No Contact")
    f.get("Get_Contact_Cases", "Case", [("ContactId", "EqualTo", R("$Record.ContactId")), ("CreatedDate", "GreaterThan", R("fxLast30Days"))],
          "Loop_Contact_Cases")
    f.loop("Loop_Contact_Cases", "Get_Contact_Cases", "Dec_Case_Is_Open", "Dec_Priority_Rule")
    f.decision("Dec_Case_Is_Open", [("Is_Open", [("Loop_Contact_Cases.IsClosed", "EqualTo", False)], "Asg_Increment_Open")], "Loop_Contact_Cases", "Closed")
    f.assign("Asg_Increment_Open", [("varOpenCaseCount", "Add", 1)], "Loop_Contact_Cases")
    f.decision("Dec_Priority_Rule", [
        ("Critical_Customer", [("varAccountRating", "EqualTo", "Hot"), ("varOpenCaseCount", "GreaterThanOrEqualTo", 3)], "Asg_Priority_High", "or"),
        ("Important_Customer", [("$Record.Origin", "EqualTo", "Phone"), ("varAccountType", "Contains", "Customer")], "Asg_Priority_Medium", "or")],
        "Asg_Priority_Low", "Standard")
    f.assign("Asg_Priority_High", [("$Record.Priority", "Assign", "High")], "Dec_Origin_Missing")
    f.assign("Asg_Priority_Medium", [("$Record.Priority", "Assign", "Medium")], "Dec_Origin_Missing")
    f.assign("Asg_Priority_Low", [("$Record.Priority", "Assign", "Low")], "Dec_Origin_Missing")
    f.decision("Dec_Origin_Missing", [("Origin_Missing", [("$Record.Origin", "IsNull", True)], "Asg_Default_Origin")], None, "Origin Set")
    f.assign("Asg_Default_Origin", [("$Record.Origin", "Assign", "Web")])
    f.start("Dec_Has_Account", obj="Case", trigger="RecordBeforeSave", record_trigger="Create")
    return f


def lead_intake():
    f = Flow("RTF_Lead_Intake_Processing", "RTF Lead Intake Processing", "rtf",
             "After-save on Lead create. Immediate: source-based follow-up Task. Async path: duplicate check against Leads and Contacts "
             "with alert. Scheduled path +3 days: cools down untouched leads.")
    f.var("varSlaDays", "Number", scale=0, default=5)
    f.var("varDuplicateLeads", "Number", scale=0, default=0)
    f.var("varMatchingContacts", "Number", scale=0, default=0)
    f.formula("fxSlaDate", "Date", "TODAY() + {!varSlaDays}")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.tt("ttDuplicateBody", "New lead {!$Record.FirstName} {!$Record.LastName} ({!$Record.Email}) matches {!varDuplicateLeads} open lead(s) and {!varMatchingContacts} contact(s).")
    f.decision("Dec_Lead_Source", [
        ("Web_Lead", [("$Record.LeadSource", "EqualTo", "Web")], "Create_Fast_Followup_Task"),
        ("Partner_Lead", [("$Record.LeadSource", "EqualTo", "Partner Referral")], "Create_Partner_Task")],
        "Asg_Standard_SLA", "Other Source")
    f.create("Create_Fast_Followup_Task", "Task", {"Subject": PFX + "Call web lead within 24h", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                                   "ActivityDate": R("fxTomorrow"), "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    f.create("Create_Partner_Task", "Task", {"Subject": PFX + "Coordinate with referring partner", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                             "ActivityDate": R("fxTomorrow"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.assign("Asg_Standard_SLA", [("varSlaDays", "Assign", 3)], "Create_Standard_Task")
    f.create("Create_Standard_Task", "Task", {"Subject": PFX + "Qualify new lead", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                              "ActivityDate": R("fxSlaDate"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    # async path
    f.decision("Dec_Has_Email", [("Email_Present", [("$Record.Email", "IsNull", False)], "Get_Duplicate_Leads")], None, "No Email")
    f.get("Get_Duplicate_Leads", "Lead", [("Email", "EqualTo", R("$Record.Email")), ("Id", "NotEqualTo", R("$Record.Id")), ("IsConverted", "EqualTo", False)],
          "Get_Matching_Contacts", "Log_Fault")
    f.get("Get_Matching_Contacts", "Contact", [("Email", "EqualTo", R("$Record.Email"))], "Asg_Duplicate_Counts", "Log_Fault")
    f.assign("Asg_Duplicate_Counts", [("varDuplicateLeads", "AssignCount", R("Get_Duplicate_Leads")),
                                      ("varMatchingContacts", "AssignCount", R("Get_Matching_Contacts"))], "Dec_Duplicate_Found")
    f.decision("Dec_Duplicate_Found", [("Duplicate", [("varDuplicateLeads", "GreaterThan", 0), ("varMatchingContacts", "GreaterThan", 0)], "Create_Duplicate_Task", "or")],
               None, "Unique")
    f.create("Create_Duplicate_Task", "Task", {"Subject": PFX + "Possible duplicate lead", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                               "Description": R("ttDuplicateBody"), "Priority": "Normal", "Status": "Not Started"},
             "Send_Duplicate_Email", "Log_Fault")
    f.email("Send_Duplicate_Email", R("$User.Email"), PFX + "Possible duplicate lead", R("ttDuplicateBody"), None, "Log_Fault")
    # scheduled path
    f.get("Get_Lead_Current", "Lead", [("Id", "EqualTo", R("$Record.Id"))], "Dec_Still_Untouched", "Log_Fault", first=True)
    f.decision("Dec_Still_Untouched", [("Untouched", [("Get_Lead_Current.IsConverted", "EqualTo", False),
                                                      ("Get_Lead_Current.Status", "EqualTo", "Open - Not Contacted")], "Update_Lead_Rating")],
               None, "Being Worked")
    f.update("Update_Lead_Rating", "Lead", [("Id", "EqualTo", R("$Record.Id"))], {"Rating": "Cold"}, "Create_Reminder_Task", "Log_Fault")
    f.create("Create_Reminder_Task", "Task", {"Subject": PFX + "Lead untouched for 3 days", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                              "ActivityDate": R("fxTomorrow"), "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Lead_Source", obj="Lead", trigger="RecordAfterSave", record_trigger="Create",
            paths=[{"async": "Dec_Has_Email"},
                   dict(name="Three_Days_After_Creation", label="3 Days After Creation", target="Get_Lead_Current", num=3, unit="Days", field="CreatedDate")])
    return f


def case_escalation():
    f = Flow("RTF_Case_High_Priority_Escalation", "RTF Case High Priority Escalation", "rtf",
             "After-save when a Case becomes High priority: routes a Task to account manager or support, collects other open high-priority "
             "cases on the account (sorted) and e-mails a digest. Scheduled path +4h after trigger marks still-open cases Escalated.")
    f.var("varContactName", "String")
    f.var("varCaseList", "String", default="")
    f.formula("fxDueToday", "Date", "TODAY()")
    f.tt("ttEscalationBody", "Case {!$Record.CaseNumber} - {!$Record.Subject} is now High priority.\nContact: {!varContactName}\n"
                             "Other open high-priority cases on the account:\n{!varCaseList}")
    f.get("Get_Contact", "Contact", [("Id", "EqualTo", R("$Record.ContactId"))], "Dec_Contact_Found", "Log_Fault", first=True)
    f.decision("Dec_Contact_Found", [("Contact_Found", [("Get_Contact", "IsNull", False)], "Asg_Contact_Info")], "Get_Account", "No Contact")
    f.assign("Asg_Contact_Info", [("varContactName", "Assign", R("Get_Contact.Name"))], "Get_Account")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], "Dec_Key_Account", "Log_Fault", first=True)
    f.decision("Dec_Key_Account", [("Key_Account", [("Get_Account", "IsNull", False), ("Get_Account.Rating", "EqualTo", "Hot")], "Create_Account_Manager_Task")],
               "Create_Support_Task", "Regular")
    f.create("Create_Account_Manager_Task", "Task", {"Subject": PFX + "Key account has a high-priority case", "WhatId": R("$Record.AccountId"),
                                                     "OwnerId": R("Get_Account.OwnerId"), "ActivityDate": R("fxDueToday"), "Priority": "High", "Status": "Not Started"},
             "Get_Related_Open_Cases", "Log_Fault")
    f.create("Create_Support_Task", "Task", {"Subject": PFX + "Work high-priority case", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.LastModifiedById"),
                                             "ActivityDate": R("fxDueToday"), "Priority": "High", "Status": "Not Started"},
             "Get_Related_Open_Cases", "Log_Fault")
    f.get("Get_Related_Open_Cases", "Case", [("AccountId", "EqualTo", R("$Record.AccountId")), ("IsClosed", "EqualTo", False),
                                             ("Priority", "EqualTo", "High"), ("Id", "NotEqualTo", R("$Record.Id"))],
          "Sort_Cases_By_Age", "Log_Fault")
    f.sort_coll("Sort_Cases_By_Age", "Get_Related_Open_Cases", "CreatedDate", "Asc", "Loop_Related_Cases", limit=10)
    f.loop("Loop_Related_Cases", "Get_Related_Open_Cases", "Asg_Append_Case", "Send_Escalation_Email")
    f.assign("Asg_Append_Case", [("varCaseList", "Add", R("Loop_Related_Cases.CaseNumber")), ("varCaseList", "Add", " ")], "Loop_Related_Cases")
    f.email("Send_Escalation_Email", R("$User.Email"), PFX + "High-priority case escalation", R("ttEscalationBody"), None, "Log_Fault")
    # scheduled path (+4h)
    f.get("Get_Case_Status", "Case", [("Id", "EqualTo", R("$Record.Id"))], "Dec_Still_Open", "Log_Fault", first=True)
    f.decision("Dec_Still_Open", [("Still_Open", [("Get_Case_Status.IsClosed", "EqualTo", False), ("Get_Case_Status.Status", "NotEqualTo", "Escalated")], "Update_Case_Escalated")],
               None, "Handled")
    f.update("Update_Case_Escalated", "Case", [("Id", "EqualTo", R("$Record.Id"))], {"Status": "Escalated"}, "Create_SLA_Breach_Task", "Log_Fault")
    f.create("Create_SLA_Breach_Task", "Task", {"Subject": PFX + "SLA breach: high-priority case open 4h+", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.LastModifiedById"),
                                                "ActivityDate": R("fxDueToday"), "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"), severity="Critical")
    f.start("Get_Contact", obj="Case", trigger="RecordAfterSave", record_trigger="CreateAndUpdate",
            filters=[("Priority", "EqualTo", "High")], changed=True,
            paths=[dict(name="Four_Hours_After_Escalation", label="4 Hours After Escalation", target="Get_Case_Status", num=4, unit="Hours", source="RecordTriggerEvent")])
    return f


ALL = [account_create, opp_closed, case_before_save, lead_intake, case_escalation]

from flowlib import Flow, R, D
from common import log_fault, PFX


def contact_email_change():
    f = Flow("RTF_Contact_Email_Change_Sync", "RTF Contact Email Change Sync", "rtf",
             "After-save on Contact update when Email changes ($Record__Prior): moves the contact's open Cases that still carry the old "
             "web e-mail to the new address (bulk update), refreshes the activity snapshot subflow and leaves a verification Task + e-mail.")
    f.var("varCase", "SObject", obj="Case")
    f.var("colCasesToUpdate", "SObject", coll=True, obj="Case")
    f.var("varCaseCount", "Number", scale=0, default=0)
    f.var("varOpenTasks", "Number", scale=0, default=0)
    f.var("varEngagement", "String")
    f.formula("fxPriorEmail", "String", "BLANKVALUE({!$Record__Prior.Email}, '(none)')")
    f.formula("fxDueDate", "Date", "TODAY() + 3")
    f.tt("ttChange", "Contact {!$Record.FirstName} {!$Record.LastName} changed e-mail from {!fxPriorEmail} to {!$Record.Email}.\n"
                     "Open cases moved to the new address: {!varCaseCount}. Open tasks: {!varOpenTasks}. Engagement: {!varEngagement}.\n"
                     "Changed by {!$User.Username}.")
    f.decision("Dec_Email_Changed", [("Email_Changed", [("$Record.Email", "NotEqualTo", R("$Record__Prior.Email"))], "Get_Open_Cases")],
               None, "Email Unchanged")
    f.get("Get_Open_Cases", "Case", [("ContactId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Loop_Cases", "Log_Fault")
    f.loop("Loop_Cases", "Get_Open_Cases", "Dec_Case_Uses_Old_Email", "Dec_Any_Cases", var="varCase")
    f.decision("Dec_Case_Uses_Old_Email", [("Uses_Old_Email", [("$Record__Prior.Email", "IsNull", False),
                                                               ("varCase.SuppliedEmail", "EqualTo", R("$Record__Prior.Email"))], "Asg_Case_Email")],
               "Loop_Cases", "Other Email")
    f.assign("Asg_Case_Email", [("varCase.SuppliedEmail", "Assign", R("$Record.Email")), ("colCasesToUpdate", "Add", R("varCase")),
                                ("varCaseCount", "Add", 1)], "Loop_Cases")
    f.decision("Dec_Any_Cases", [("Has_Cases", [("varCaseCount", "GreaterThan", 0)], "Update_Cases")], "Sub_Activity_Snapshot", "None")
    f.update("Update_Cases", input_ref="colCasesToUpdate", nxt="Sub_Activity_Snapshot", fault="Log_Fault")
    f.subflow("Sub_Activity_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("$Record.Id")},
              {"outOpenTasks": "varOpenTasks", "outEngagement": "varEngagement"}, "Create_Verification_Task")
    f.create("Create_Verification_Task", "Task", {"Subject": PFX + "Contact e-mail changed - verify", "WhoId": R("$Record.Id"),
                                                  "OwnerId": R("$Record.OwnerId"), "Description": R("ttChange"), "ActivityDate": R("fxDueDate"),
                                                  "Priority": "Normal", "Status": "Not Started"}, "Dec_Had_Old_Email", "Log_Fault")
    f.decision("Dec_Had_Old_Email", [("Replaced_Address", [("$Record__Prior.Email", "IsNull", False)], "Send_Change_Email")], None, "First Address")
    f.email("Send_Change_Email", R("$User.Email"), PFX + "Contact e-mail address changed", R("ttChange"), None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Email_Changed", obj="Contact", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("Email", "IsNull", False)])
    return f


def lead_hot():
    f = Flow("RTF_Lead_Hot_Rating_Acceleration", "RTF Lead Hot Rating Acceleration", "rtf",
             "After-save when an unconverted Lead becomes Hot: raises its open demo Tasks to High (bulk update), alerts on a Cold-to-Hot "
             "jump ($Record__Prior) and creates a call Task. Scheduled path +2 days: if still untouched, stalled-lead Task and contact "
             "snapshot for a matching Contact.")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varRaised", "Number", scale=0, default=0)
    f.var("varEngagement", "String")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.formula("fxPriorRating", "String", "BLANKVALUE(TEXT({!$Record__Prior.Rating}), 'blank')")
    f.tt("ttHot", "Lead {!$Record.FirstName} {!$Record.LastName} ({!$Record.Company}) is now rated Hot (previous rating: {!fxPriorRating}).\n"
                  "Open demo tasks raised to High priority: {!varRaised}.")
    f.get("Get_Open_Lead_Tasks", "Task", [("WhoId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False), ("Subject", "StartsWith", PFX)],
          "Loop_Tasks", "Log_Fault")
    f.loop("Loop_Tasks", "Get_Open_Lead_Tasks", "Dec_Task_Not_High", "Dec_Any_Raised", var="varTask")
    f.decision("Dec_Task_Not_High", [("Not_High", [("varTask.Priority", "NotEqualTo", "High")], "Asg_Raise_Task")], "Loop_Tasks", "Already High")
    f.assign("Asg_Raise_Task", [("varTask.Priority", "Assign", "High"), ("varTask.ActivityDate", "Assign", R("fxTomorrow")),
                                ("colTasksToUpdate", "Add", R("varTask")), ("varRaised", "Add", 1)], "Loop_Tasks")
    f.decision("Dec_Any_Raised", [("Has_Raised", [("varRaised", "GreaterThan", 0)], "Update_Tasks")], "Dec_Prior_Rating", "None")
    f.update("Update_Tasks", input_ref="colTasksToUpdate", nxt="Dec_Prior_Rating", fault="Log_Fault")
    f.decision("Dec_Prior_Rating", [("Was_Cold", [("$Record__Prior.Rating", "EqualTo", "Cold")], "Send_Jump_Email")], "Create_Call_Task", "Not Cold Before")
    f.email("Send_Jump_Email", R("$User.Email"), PFX + "Lead jumped from Cold to Hot", R("ttHot"), "Create_Call_Task", "Log_Fault")
    f.create("Create_Call_Task", "Task", {"Subject": PFX + "Call hot lead today", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.LastModifiedById"),
                                          "Description": R("ttHot"), "ActivityDate": R("$Flow.CurrentDate"), "Priority": "High", "Status": "Not Started"},
             None, "Log_Fault")
    # scheduled path (+2 days after the rating change)
    f.get("Get_Lead_Later", "Lead", [("Id", "EqualTo", R("$Record.Id"))], "Dec_Still_Untouched", "Log_Fault", first=True)
    f.decision("Dec_Still_Untouched", [("Untouched", [("Get_Lead_Later.IsConverted", "EqualTo", False),
                                                      ("Get_Lead_Later.Status", "EqualTo", "Open - Not Contacted")], "Create_Stalled_Task")],
               None, "Being Worked")
    f.create("Create_Stalled_Task", "Task", {"Subject": PFX + "Hot lead still not contacted after 2 days", "WhoId": R("$Record.Id"),
                                             "OwnerId": R("$Record.LastModifiedById"), "ActivityDate": R("fxTomorrow"), "Priority": "High",
                                             "Status": "Not Started"}, "Dec_Has_Email", "Log_Fault")
    f.decision("Dec_Has_Email", [("Email_Present", [("Get_Lead_Later.Email", "IsNull", False)], "Get_Matching_Contact")], None, "No Email")
    f.get("Get_Matching_Contact", "Contact", [("Email", "EqualTo", R("Get_Lead_Later.Email"))], "Dec_Contact_Found", "Log_Fault", first=True)
    f.decision("Dec_Contact_Found", [("Contact_Found", [("Get_Matching_Contact", "IsNull", False)], "Sub_Contact_Snapshot")], None, "No Contact")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("Get_Matching_Contact.Id")}, {"outEngagement": "varEngagement"})
    log_fault(f, record=R("$Record.Id"))
    f.start("Get_Open_Lead_Tasks", obj="Lead", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("Rating", "EqualTo", "Hot"), ("IsConverted", "EqualTo", False)], changed=True,
            paths=[dict(name="Two_Days_After_Hot", label="2 Days After Hot", target="Get_Lead_Later", num=2, unit="Days", source="RecordTriggerEvent")])
    return f


def opp_contact_roles():
    f = Flow("RTF_Opportunity_Create_Contact_Roles", "RTF Opportunity Create Contact Roles", "rtf",
             "After-save on Opportunity create (with Account, no roles yet): adds Decision Maker contact roles for senior contacts of the "
             "account (collection filter on Title, bulk create) or a Task to identify them. Async path: pipeline summary subflow and a "
             "capacity Task when the account has many open deals.")
    f.var("varContact", "SObject", obj="Contact")
    f.var("varRole", "SObject", obj="OpportunityContactRole")
    f.var("colRoles", "SObject", coll=True, obj="OpportunityContactRole")
    f.var("varExistingRoles", "Number", scale=0, default=0)
    f.var("varRoleCount", "Number", scale=0, default=0)
    f.var("varPipeline", "Currency", scale=2)
    f.var("varDealCount", "Number", scale=0, default=0)
    f.var("varLateStage", "Number", scale=0, default=0)
    f.formula("fxDueDate", "Date", "TODAY() + 5")
    f.tt("ttPipeline", "New opportunity {!$Record.Name} was added. Account pipeline: {!varPipeline} across {!varDealCount} open deal(s), "
                       "{!varLateStage} in late stage. Please check the team has capacity.")
    f.get("Get_Existing_Roles", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("$Record.Id"))], "Asg_Existing_Count", "Log_Fault")
    f.assign("Asg_Existing_Count", [("varExistingRoles", "AssignCount", R("Get_Existing_Roles"))], "Dec_Roles_Exist")
    f.decision("Dec_Roles_Exist", [("Has_Roles", [("varExistingRoles", "GreaterThan", 0)], None)], "Get_Account_Contacts", "No Roles")
    f.get("Get_Account_Contacts", "Contact", [("AccountId", "EqualTo", R("$Record.AccountId"))], "Filter_Senior_Contacts", "Log_Fault",
          sort="LastModifiedDate", order="Desc")
    f.filter_coll("Filter_Senior_Contacts", "Get_Account_Contacts", "Contact",
                  [("Title", "Contains", "Director"), ("Title", "Contains", "Chief"), ("Title", "Contains", "VP"), ("Email", "IsNull", False)],
                  "Loop_Senior_Contacts", logic="(1 OR 2 OR 3) AND 4")
    f.loop("Loop_Senior_Contacts", "Filter_Senior_Contacts", "Asg_Role", "Dec_Any_Roles", var="varContact")
    f.assign("Asg_Role", [("varRole.OpportunityId", "Assign", R("$Record.Id")), ("varRole.ContactId", "Assign", R("varContact.Id")),
                          ("varRole.Role", "Assign", "Decision Maker"), ("colRoles", "Add", R("varRole")), ("varRoleCount", "Add", 1)],
             "Loop_Senior_Contacts")
    f.decision("Dec_Any_Roles", [("Has_Senior_Contacts", [("varRoleCount", "GreaterThan", 0)], "Create_Contact_Roles")],
               "Create_Role_Review_Task", "No Senior Contacts")
    f.create("Create_Contact_Roles", input_ref="colRoles", fault="Log_Fault")
    f.create("Create_Role_Review_Task", "Task", {"Subject": PFX + "Identify decision makers for new deal", "WhatId": R("$Record.Id"),
                                                 "OwnerId": R("$Record.OwnerId"), "ActivityDate": R("fxDueDate"), "Priority": "Normal",
                                                 "Status": "Not Started"}, None, "Log_Fault")
    # async path
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("$Record.AccountId"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline", "outDealCount": "varDealCount", "outLateStageCount": "varLateStage"}, "Dec_Many_Deals")
    f.decision("Dec_Many_Deals", [("Many_Open_Deals", [("varDealCount", "GreaterThanOrEqualTo", 5)], "Create_Capacity_Task")], None, "Normal Load")
    f.create("Create_Capacity_Task", "Task", {"Subject": PFX + "Account has 5+ open deals - check capacity", "WhatId": R("$Record.AccountId"),
                                              "OwnerId": R("$Record.OwnerId"), "Description": R("ttPipeline"), "ActivityDate": R("fxDueDate"),
                                              "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Get_Existing_Roles", obj="Opportunity", trigger="RecordAfterSave", record_trigger="Create",
            filters=[("AccountId", "IsNull", False)], paths=[{"async": "Sub_Pipeline_Summary"}])
    return f


def oli_before_delete():
    f = Flow("RTF_Opportunity_Product_Before_Delete", "RTF Opportunity Product Before Delete", "rtf",
             "Before-delete on OpportunityLineItem: on closed deals raises an alert Task + e-mail; on open deals totals the remaining "
             "product lines and creates a Task when the last product or a large line is removed, then refreshes the pipeline summary.")
    f.var("varItem", "SObject", obj="OpportunityLineItem")
    f.var("varRemainingCount", "Number", scale=0, default=0)
    f.var("varRemainingTotal", "Currency", scale=2, default=0)
    f.formula("fxDeletedValue", "Currency", "BLANKVALUE({!$Record.TotalPrice}, 0)", scale=2)
    f.formula("fxItemValue", "Currency", "BLANKVALUE({!varItem.TotalPrice}, 0)", scale=2)
    f.formula("fxDueDate", "Date", "TODAY() + 2")
    f.tt("ttRemoval", "A product line (quantity {!$Record.Quantity}, total {!fxDeletedValue}) was removed from opportunity "
                      "{!Get_Opportunity.Name} by {!$User.Username}.\nRemaining product lines: {!varRemainingCount}, total {!varRemainingTotal}.")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("$Record.OpportunityId"))], "Dec_Deal_State", "Log_Fault", first=True)
    f.decision("Dec_Deal_State", [
        ("Closed_Deal", [("Get_Opportunity.IsClosed", "EqualTo", True)], "Create_Closed_Deal_Task"),
        ("Open_Deal", [("Get_Opportunity.IsClosed", "EqualTo", False)], "Get_Remaining_Items")], None, "Not Found")
    f.create("Create_Closed_Deal_Task", "Task", {"Subject": PFX + "Product removed from a closed deal", "WhatId": R("$Record.OpportunityId"),
                                                 "OwnerId": R("Get_Opportunity.OwnerId"), "Description": R("ttRemoval"), "ActivityDate": R("fxDueDate"),
                                                 "Priority": "High", "Status": "Not Started"}, "Send_Removal_Email", "Log_Fault")
    f.email("Send_Removal_Email", R("$User.Email"), PFX + "Product removed from closed opportunity", R("ttRemoval"), None, "Log_Fault")
    f.get("Get_Remaining_Items", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("$Record.OpportunityId")), ("Id", "NotEqualTo", R("$Record.Id"))],
          "Loop_Items", "Log_Fault")
    f.loop("Loop_Items", "Get_Remaining_Items", "Asg_Accumulate", "Dec_Last_Product", var="varItem")
    f.assign("Asg_Accumulate", [("varRemainingTotal", "Add", R("fxItemValue")), ("varRemainingCount", "Add", 1)], "Loop_Items")
    f.decision("Dec_Last_Product", [("Last_Product", [("varRemainingCount", "EqualTo", 0)], "Create_Empty_Deal_Task")], "Dec_Large_Removal", "Products Remain")
    f.create("Create_Empty_Deal_Task", "Task", {"Subject": PFX + "Opportunity has no products left", "WhatId": R("$Record.OpportunityId"),
                                                "OwnerId": R("Get_Opportunity.OwnerId"), "Description": R("ttRemoval"), "ActivityDate": R("fxDueDate"),
                                                "Priority": "Normal", "Status": "Not Started"}, "Dec_Has_Account", "Log_Fault")
    f.decision("Dec_Large_Removal", [("Large_Line", [("fxDeletedValue", "GreaterThanOrEqualTo", 10000)], "Create_Large_Removal_Task")],
               "Dec_Has_Account", "Small Line")
    f.create("Create_Large_Removal_Task", "Task", {"Subject": PFX + "Large product line removed - review amount", "WhatId": R("$Record.OpportunityId"),
                                                   "OwnerId": R("Get_Opportunity.OwnerId"), "Description": R("ttRemoval"), "ActivityDate": R("fxDueDate"),
                                                   "Priority": "Normal", "Status": "Not Started"}, "Dec_Has_Account", "Log_Fault")
    f.decision("Dec_Has_Account", [("Has_Account", [("Get_Opportunity.AccountId", "IsNull", False)], "Sub_Pipeline_Summary")], None, "No Account")
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("Get_Opportunity.AccountId"), "inCreateTask": False})
    log_fault(f, record=R("$Record.OpportunityId"))
    f.start("Get_Opportunity", obj="OpportunityLineItem", trigger="RecordBeforeDelete", record_trigger="Delete")
    return f


def case_email_matcher():
    f = Flow("RTF_Case_Email_Contact_Matcher", "RTF Case Email Contact Matcher", "rtf",
             "After-save on Case create without Contact but with a web e-mail: immediate triage Task (and alert for High priority). "
             "Async path matches Contacts by SuppliedEmail: one match links the Case and runs the contact snapshot; several matches "
             "create a review Task listing candidates; none creates a no-match Task.")
    f.var("varContact", "SObject", obj="Contact")
    f.var("varMatchCount", "Number", scale=0, default=0)
    f.var("varBestContactId", "String")
    f.var("varBestAccountId", "String")
    f.var("varCandidateList", "String", default="")
    f.var("varEngagement", "String")
    f.formula("fxDueToday", "Date", "TODAY()")
    f.tt("ttUnlinked", "Case {!$Record.CaseNumber} '{!$Record.Subject}' (priority {!$Record.Priority}) arrived from {!$Record.SuppliedEmail} without a contact.")
    f.tt("ttCandidates", "Case {!$Record.CaseNumber} from {!$Record.SuppliedEmail} matches {!varMatchCount} contacts. Pick the right one:\n{!varCandidateList}")
    f.decision("Dec_Priority_High", [("High_Priority", [("$Record.Priority", "EqualTo", "High")], "Send_Unlinked_Alert")], "Create_Triage_Task", "Normal")
    f.email("Send_Unlinked_Alert", R("$User.Email"), PFX + "High-priority case without contact", R("ttUnlinked"), "Create_Triage_Task", "Log_Fault")
    f.create("Create_Triage_Task", "Task", {"Subject": PFX + "Triage case without contact", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                            "Description": R("ttUnlinked"), "ActivityDate": R("fxDueToday"), "Priority": "Normal",
                                            "Status": "Not Started"}, None, "Log_Fault")
    # async path
    f.get("Get_Matching_Contacts", "Contact", [("Email", "EqualTo", R("$Record.SuppliedEmail"))], "Asg_Match_Count", "Log_Fault",
          sort="LastModifiedDate", order="Asc")
    f.assign("Asg_Match_Count", [("varMatchCount", "AssignCount", R("Get_Matching_Contacts"))], "Loop_Candidates")
    f.loop("Loop_Candidates", "Get_Matching_Contacts", "Asg_Candidate", "Dec_Match_Result", var="varContact")
    f.assign("Asg_Candidate", [("varBestContactId", "Assign", R("varContact.Id")), ("varBestAccountId", "Assign", R("varContact.AccountId")),
                               ("varCandidateList", "Add", R("varContact.Name")), ("varCandidateList", "Add", " / ")], "Loop_Candidates")
    f.decision("Dec_Match_Result", [
        ("Single_Match", [("varMatchCount", "EqualTo", 1)], "Update_Case_Contact"),
        ("Multiple_Matches", [("varMatchCount", "GreaterThan", 1)], "Create_Review_Task")], "Create_No_Match_Task", "No Match")
    f.update("Update_Case_Contact", "Case", [("Id", "EqualTo", R("$Record.Id"))], {"ContactId": R("varBestContactId"), "AccountId": R("varBestAccountId")},
             "Sub_Contact_Snapshot", "Log_Fault")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("varBestContactId")}, {"outEngagement": "varEngagement"})
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Choose contact for case (several matches)", "WhatId": R("$Record.Id"),
                                            "OwnerId": R("$Record.CreatedById"), "Description": R("ttCandidates"), "ActivityDate": R("fxDueToday"),
                                            "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.create("Create_No_Match_Task", "Task", {"Subject": PFX + "Case sender is not a known contact", "WhatId": R("$Record.Id"),
                                              "OwnerId": R("$Record.CreatedById"), "Description": R("ttUnlinked"), "ActivityDate": R("fxDueToday"),
                                              "Priority": "Low", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Priority_High", obj="Case", trigger="RecordAfterSave", record_trigger="Create",
            filters=[("ContactId", "IsNull", True), ("SuppliedEmail", "IsNull", False)], paths=[{"async": "Get_Matching_Contacts"}])
    return f


def task_before_save():
    f = Flow("RTF_Task_Before_Save_Workload_Balancer", "RTF Task Before Save Workload Balancer", "rtf",
             "Before-save on open Task create: defaults a missing due date from Priority, raises Priority for tasks on Opportunities "
             "closing within 7 days, and pushes the due date one day out when the owner already has 10+ open tasks that day.")
    f.var("varTask", "SObject", obj="Task")
    f.var("varSameDayCount", "Number", scale=0, default=0)
    f.formula("fxDueTomorrow", "Date", "TODAY() + 1")
    f.formula("fxDueLater", "Date", "TODAY() + 5")
    f.formula("fxClosingSoon", "Date", "TODAY() + 7")
    f.formula("fxNextDay", "Date", "{!$Record.ActivityDate} + 1")
    f.formula("fxWhatPrefix", "String", "LEFT({!$Record.WhatId}, 3)")
    f.formula("fxBalanceNote", "String", "LEFT(BLANKVALUE({!$Record.Description}, '') & ' [Due date moved +1 day: owner already had ' "
                                         "& TEXT({!varSameDayCount}) & ' open tasks that day]', 32000)")
    f.decision("Dec_Due_Date_Missing", [("Due_Date_Missing", [("$Record.ActivityDate", "IsNull", True)], "Dec_Priority_For_Default")],
               "Dec_Related_To_Opp", "Due Date Set")
    f.decision("Dec_Priority_For_Default", [("Is_High", [("$Record.Priority", "EqualTo", "High")], "Asg_Due_Tomorrow")], "Asg_Due_Later", "Normal Or Low")
    f.assign("Asg_Due_Tomorrow", [("$Record.ActivityDate", "Assign", R("fxDueTomorrow"))], "Dec_Related_To_Opp")
    f.assign("Asg_Due_Later", [("$Record.ActivityDate", "Assign", R("fxDueLater"))], "Dec_Related_To_Opp")
    f.decision("Dec_Related_To_Opp", [("Opportunity_Task", [("fxWhatPrefix", "EqualTo", "006")], "Get_Opportunity")], "Get_Same_Day_Tasks", "Other")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("$Record.WhatId"))], "Dec_Closing_Soon", first=True)
    f.decision("Dec_Closing_Soon", [("Closing_Soon", [("Get_Opportunity", "IsNull", False), ("Get_Opportunity.IsClosed", "EqualTo", False),
                                                      ("Get_Opportunity.CloseDate", "LessThanOrEqualTo", R("fxClosingSoon"))], "Asg_Priority_High")],
               "Get_Same_Day_Tasks", "Not Urgent")
    f.assign("Asg_Priority_High", [("$Record.Priority", "Assign", "High")], "Get_Same_Day_Tasks")
    f.get("Get_Same_Day_Tasks", "Task", [("OwnerId", "EqualTo", R("$Record.OwnerId")), ("ActivityDate", "EqualTo", R("$Record.ActivityDate")),
                                         ("IsClosed", "EqualTo", False)], "Loop_Same_Day")
    f.loop("Loop_Same_Day", "Get_Same_Day_Tasks", "Asg_Count_Task", "Dec_Overloaded", var="varTask")
    f.assign("Asg_Count_Task", [("varSameDayCount", "Add", 1)], "Loop_Same_Day")
    f.decision("Dec_Overloaded", [("Overloaded", [("varSameDayCount", "GreaterThanOrEqualTo", 10), ("$Record.Priority", "NotEqualTo", "High")],
                                   "Asg_Push_Due_Date")], None, "Capacity OK")
    f.assign("Asg_Push_Due_Date", [("$Record.Description", "Assign", R("fxBalanceNote")), ("$Record.ActivityDate", "Assign", R("fxNextDay"))])
    f.start("Dec_Due_Date_Missing", obj="Task", trigger="RecordBeforeSave", record_trigger="Create",
            filters=[("Status", "NotEqualTo", "Completed")])
    return f


def event_prep():
    f = Flow("RTF_Event_Meeting_Preparation", "RTF Event Meeting Preparation", "rtf",
             "After-save on Event create: for meetings with a Contact counts other meetings with that contact within a week and runs "
             "the activity snapshot subflow, then creates a preparation Task. Scheduled path 1 day before StartDateTime e-mails the "
             "organizer if the preparation Task is still open.")
    f.var("varOtherMeetings", "Number", scale=0, default=0)
    f.var("varOpenTasks", "Number", scale=0, default=0)
    f.var("varEngagement", "String", default="n/a")
    f.var("varOpenPrepCount", "Number", scale=0, default=0)
    f.formula("fxWhoPrefix", "String", "LEFT({!$Record.WhoId}, 3)")
    f.formula("fxWeekBefore", "DateTime", "{!$Record.StartDateTime} - 7")
    f.formula("fxWeekAfter", "DateTime", "{!$Record.StartDateTime} + 7")
    f.formula("fxPrepDue", "Date", "DATEVALUE({!$Record.StartDateTime}) - 1")
    f.tt("ttPrep", "Meeting '{!$Record.Subject}' starts {!$Record.StartDateTime}.\nContact engagement: {!varEngagement}; contact open tasks: "
                   "{!varOpenTasks}; other meetings with this contact within a week: {!varOtherMeetings}.")
    f.tt("ttReminder", "Your meeting '{!$Record.Subject}' starts {!$Record.StartDateTime} and the preparation task is still open.")
    f.decision("Dec_Who_Type", [("Contact_Meeting", [("fxWhoPrefix", "EqualTo", "003")], "Get_Nearby_Meetings")], "Create_Prep_Task", "No Contact")
    f.get("Get_Nearby_Meetings", "Event", [("WhoId", "EqualTo", R("$Record.WhoId")), ("StartDateTime", "GreaterThan", R("fxWeekBefore")),
                                           ("StartDateTime", "LessThan", R("fxWeekAfter")), ("Id", "NotEqualTo", R("$Record.Id"))],
          "Loop_Meetings", "Log_Fault")
    f.loop("Loop_Meetings", "Get_Nearby_Meetings", "Asg_Count_Meeting", "Sub_Contact_Snapshot")
    f.assign("Asg_Count_Meeting", [("varOtherMeetings", "Add", 1)], "Loop_Meetings")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("$Record.WhoId")},
              {"outOpenTasks": "varOpenTasks", "outEngagement": "varEngagement"}, "Create_Prep_Task")
    f.create("Create_Prep_Task", "Task", {"Subject": PFX + "Prepare for meeting", "WhoId": R("$Record.WhoId"), "WhatId": R("$Record.WhatId"),
                                          "OwnerId": R("$Record.CreatedById"), "Description": R("ttPrep"), "ActivityDate": R("fxPrepDue"),
                                          "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    # scheduled path (1 day before start)
    f.get("Get_Organizer", "User", [("Id", "EqualTo", R("$Record.CreatedById"))], "Dec_Organizer_Active", "Log_Fault", first=True)
    f.decision("Dec_Organizer_Active", [("Active", [("Get_Organizer", "IsNull", False), ("Get_Organizer.IsActive", "EqualTo", True)], "Get_Open_Prep_Tasks")],
               None, "Inactive")
    f.get("Get_Open_Prep_Tasks", "Task", [("OwnerId", "EqualTo", R("$Record.CreatedById")), ("Subject", "EqualTo", PFX + "Prepare for meeting"),
                                          ("ActivityDate", "EqualTo", R("fxPrepDue")), ("IsClosed", "EqualTo", False)],
          "Asg_Open_Prep_Count", "Log_Fault")
    f.assign("Asg_Open_Prep_Count", [("varOpenPrepCount", "AssignCount", R("Get_Open_Prep_Tasks"))], "Dec_Prep_Open")
    f.decision("Dec_Prep_Open", [("Prep_Open", [("varOpenPrepCount", "GreaterThan", 0)], "Send_Reminder_Email")], None, "Prepared")
    f.email("Send_Reminder_Email", R("Get_Organizer.Email"), PFX + "Meeting tomorrow - preparation still open", R("ttReminder"), None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Who_Type", obj="Event", trigger="RecordAfterSave", record_trigger="Create",
            filters=[("StartDateTime", "IsNull", False), ("IsChild", "EqualTo", False)],
            paths=[dict(name="One_Day_Before_Start", label="1 Day Before Start", target="Get_Organizer", num=-1, unit="Days", field="StartDateTime")])
    return f


def contract_activation():
    f = Flow("RTF_Contract_Activation_Checkin", "RTF Contract Activation Checkin", "rtf",
             "After-save when a Contract becomes Activated: totals the account's other active contracts (loop), creates a kickoff or "
             "expansion Task and e-mail. Scheduled path 30 days after ActivatedDate: account health subflow + case count since "
             "activation decide between an at-risk and a routine check-in Task.")
    f.var("varContract", "SObject", obj="Contract")
    f.var("varActiveCount", "Number", scale=0, default=0)
    f.var("varTotalTerm", "Number", scale=0, default=0)
    f.var("varCaseCount", "Number", scale=0, default=0)
    f.var("varHealthScore", "Number", scale=0, default=0)
    f.var("varHealthRating", "String")
    f.formula("fxTerm", "Number", "BLANKVALUE({!varContract.ContractTerm}, 0)", scale=0)
    f.formula("fxDueDate", "Date", "TODAY() + 7")
    f.tt("ttActivation", "Contract {!$Record.ContractNumber} was activated for {!$Record.ContractTerm} month(s).\n"
                         "Other active contracts on the account: {!varActiveCount} covering {!varTotalTerm} month(s) in total.")
    f.tt("ttCheckin", "30-day check-in for contract {!$Record.ContractNumber}: account health {!varHealthScore} ({!varHealthRating}), "
                      "{!varCaseCount} case(s) opened since activation.")
    f.get("Get_Other_Active_Contracts", "Contract", [("AccountId", "EqualTo", R("$Record.AccountId")), ("Status", "EqualTo", "Activated"),
                                                     ("Id", "NotEqualTo", R("$Record.Id"))], "Loop_Contracts", "Log_Fault")
    f.loop("Loop_Contracts", "Get_Other_Active_Contracts", "Asg_Sum_Term", "Dec_First_Contract", var="varContract")
    f.assign("Asg_Sum_Term", [("varActiveCount", "Add", 1), ("varTotalTerm", "Add", R("fxTerm"))], "Loop_Contracts")
    f.decision("Dec_First_Contract", [("First_Contract", [("varActiveCount", "EqualTo", 0)], "Create_Kickoff_Task")], "Create_Expansion_Task", "Existing Customer")
    f.create("Create_Kickoff_Task", "Task", {"Subject": PFX + "Kick off first contract", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                             "Description": R("ttActivation"), "ActivityDate": R("fxDueDate"), "Priority": "High", "Status": "Not Started"},
             "Send_Activation_Email", "Log_Fault")
    f.create("Create_Expansion_Task", "Task", {"Subject": PFX + "Review contract portfolio after new activation", "WhatId": R("$Record.Id"),
                                               "OwnerId": R("$Record.OwnerId"), "Description": R("ttActivation"), "ActivityDate": R("fxDueDate"),
                                               "Priority": "Normal", "Status": "Not Started"}, "Send_Activation_Email", "Log_Fault")
    f.email("Send_Activation_Email", R("$User.Email"), PFX + "Contract activated", R("ttActivation"), None, "Log_Fault")
    # scheduled path (+30 days after activation)
    f.subflow("Sub_Account_Health", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.AccountId")},
              {"outScore": "varHealthScore", "outRating": "varHealthRating"}, "Get_Cases_Since_Activation")
    f.get("Get_Cases_Since_Activation", "Case", [("AccountId", "EqualTo", R("$Record.AccountId")), ("CreatedDate", "GreaterThanOrEqualTo", R("$Record.ActivatedDate"))],
          "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("varCaseCount", "AssignCount", R("Get_Cases_Since_Activation"))], "Dec_Checkin_Outcome")
    f.decision("Dec_Checkin_Outcome", [("At_Risk", [("varCaseCount", "GreaterThanOrEqualTo", 3), ("varHealthScore", "LessThan", 40)], "Create_Risk_Task", "or")],
               "Create_Checkin_Task", "Healthy")
    f.create("Create_Risk_Task", "Task", {"Subject": PFX + "New contract at risk after 30 days", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                          "Description": R("ttCheckin"), "ActivityDate": R("fxDueDate"), "Priority": "High", "Status": "Not Started"},
             None, "Log_Fault")
    f.create("Create_Checkin_Task", "Task", {"Subject": PFX + "30-day contract check-in", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                             "Description": R("ttCheckin"), "ActivityDate": R("fxDueDate"), "Priority": "Low", "Status": "Not Started"},
             None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Get_Other_Active_Contracts", obj="Contract", trigger="RecordAfterSave", record_trigger="CreateAndUpdate",
            filters=[("Status", "EqualTo", "Activated")], changed=True,
            paths=[dict(name="Thirty_Days_After_Activation", label="30 Days After Activation", target="Sub_Account_Health",
                        num=30, unit="Days", field="ActivatedDate")])
    return f


def asset_renewal():
    f = Flow("RTF_Asset_Usage_End_Renewal", "RTF Asset Usage End Renewal", "rtf",
             "After-save when an Asset gets a UsageEndDate: sums the account's own (non-competitor) assets ending within 90 days "
             "(collection filter + loop) and suggests a bundled renewal. Scheduled path 14 days before UsageEndDate creates a renewal "
             "Opportunity (if none open) and refreshes the pipeline summary.")
    f.var("varAsset", "SObject", obj="Asset")
    f.var("varExpiringCount", "Number", scale=0, default=0)
    f.var("varExpiringValue", "Currency", scale=2, default=0)
    f.formula("fxIn90Days", "Date", "TODAY() + 90")
    f.formula("fxAssetValue", "Currency", "BLANKVALUE({!varAsset.Price}, 0) * BLANKVALUE({!varAsset.Quantity}, 1)", scale=2)
    f.formula("fxRenewalName", "String", f"LEFT('{PFX}Renewal - ' & {{!$Record.Name}}, 120)")
    f.formula("fxDueDate", "Date", "TODAY() + 7")
    f.tt("ttExpiring", "Asset {!$Record.Name} usage ends {!$Record.UsageEndDate}. Own assets on the account ending within 90 days: "
                       "{!varExpiringCount} with a value of {!varExpiringValue}. Consider one bundled renewal.")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("$Record.AccountId"))], "Get_Expiring_Assets", "Log_Fault", first=True)
    f.get("Get_Expiring_Assets", "Asset", [("AccountId", "EqualTo", R("$Record.AccountId")), ("UsageEndDate", "GreaterThanOrEqualTo", R("$Flow.CurrentDate")),
                                           ("UsageEndDate", "LessThanOrEqualTo", R("fxIn90Days"))], "Filter_Own_Assets", "Log_Fault")
    f.filter_coll("Filter_Own_Assets", "Get_Expiring_Assets", "Asset", [("IsCompetitorProduct", "EqualTo", False)], "Loop_Assets")
    f.loop("Loop_Assets", "Filter_Own_Assets", "Asg_Add_Value", "Dec_Bundle_Renewal", var="varAsset")
    f.assign("Asg_Add_Value", [("varExpiringCount", "Add", 1), ("varExpiringValue", "Add", R("fxAssetValue"))], "Loop_Assets")
    f.decision("Dec_Bundle_Renewal", [("Bundle_Candidate", [("varExpiringCount", "GreaterThanOrEqualTo", 3), ("Get_Account", "IsNull", False)],
                                       "Create_Bundle_Task")], None, "Single Renewal")
    f.create("Create_Bundle_Task", "Task", {"Subject": PFX + "Bundle upcoming asset renewals", "WhatId": R("$Record.AccountId"),
                                            "OwnerId": R("Get_Account.OwnerId"), "Description": R("ttExpiring"), "ActivityDate": R("fxDueDate"),
                                            "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    # scheduled path (14 days before usage end)
    f.get("Get_Asset_Later", "Asset", [("Id", "EqualTo", R("$Record.Id"))], "Dec_Still_Due", "Log_Fault", first=True)
    f.decision("Dec_Still_Due", [("Still_Due", [("Get_Asset_Later.UsageEndDate", "GreaterThanOrEqualTo", R("$Flow.CurrentDate")),
                                                ("Get_Asset_Later.IsCompetitorProduct", "EqualTo", False)], "Get_Open_Renewal")], None, "Not Due")
    f.get("Get_Open_Renewal", "Opportunity", [("AccountId", "EqualTo", R("$Record.AccountId")), ("Name", "EqualTo", R("fxRenewalName")),
                                              ("IsClosed", "EqualTo", False)], "Dec_Renewal_Exists", "Log_Fault", first=True)
    f.decision("Dec_Renewal_Exists", [("Renewal_Exists", [("Get_Open_Renewal", "IsNull", False)], None)], "Create_Renewal_Opportunity", "No Renewal")
    f.create("Create_Renewal_Opportunity", "Opportunity", {"Name": R("fxRenewalName"), "AccountId": R("$Record.AccountId"), "StageName": "Qualification",
                                                           "CloseDate": R("Get_Asset_Later.UsageEndDate"), "OwnerId": R("Get_Asset_Later.OwnerId")},
             "Sub_Pipeline_Summary", "Log_Fault")
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("$Record.AccountId"), "inCreateTask": False})
    log_fault(f, record=R("$Record.Id"))
    f.start("Get_Account", obj="Asset", trigger="RecordAfterSave", record_trigger="CreateAndUpdate",
            filters=[("UsageEndDate", "IsNull", False), ("AccountId", "IsNull", False)], changed=True,
            paths=[dict(name="Two_Weeks_Before_Usage_End", label="2 Weeks Before Usage End", target="Get_Asset_Later",
                        num=-14, unit="Days", field="UsageEndDate")])
    return f


def account_became_customer():
    f = Flow("RTF_Account_Became_Customer_Welcome", "RTF Account Became Customer Welcome", "rtf",
             "After-save when an Account's Type changes to a Customer value: if it was a Prospect ($Record__Prior), creates welcome-call "
             "Tasks for up to 5 contacts with e-mail (sort + loop + bulk create), otherwise a type-change Task; notifies by e-mail. "
             "Async path: contact normalizer + health calculator subflows, low-health Task.")
    f.var("varContact", "SObject", obj="Contact")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasks", "SObject", coll=True, obj="Task")
    f.var("varTaskCount", "Number", scale=0, default=0)
    f.var("varUpdatedContacts", "Number", scale=0, default=0)
    f.var("varHealthScore", "Number", scale=0, default=0)
    f.var("varHealthRating", "String")
    f.formula("fxDueDate", "Date", "TODAY() + 3")
    f.formula("fxPriorType", "String", "BLANKVALUE(TEXT({!$Record__Prior.Type}), 'blank')")
    f.formula("fxWelcomeSubject", "String", f"LEFT('{PFX}Welcome call - ' & {{!varContact.FirstName}} & ' ' & {{!varContact.LastName}}, 255)")
    f.tt("ttWelcome", "Account {!$Record.Name} became a customer ({!$Record.Type}; previous type: {!fxPriorType}). Welcome tasks created: {!varTaskCount}.")
    f.tt("ttHealth", "New customer {!$Record.Name} starts with a low health score ({!varHealthScore}, {!varHealthRating}). "
                     "Contacts normalized: {!varUpdatedContacts}.")
    f.decision("Dec_Previous_Type", [("From_Prospect", [("$Record__Prior.Type", "EqualTo", "Prospect")], "Get_Contacts")],
               "Create_Type_Change_Task", "Other Previous Type")
    f.get("Get_Contacts", "Contact", [("AccountId", "EqualTo", R("$Record.Id")), ("Email", "IsNull", False)], "Sort_Contacts", "Log_Fault")
    f.sort_coll("Sort_Contacts", "Get_Contacts", "CreatedDate", "Asc", "Loop_Contacts", limit=5)
    f.loop("Loop_Contacts", "Get_Contacts", "Asg_Welcome_Task", "Dec_Any_Contacts", var="varContact")
    f.assign("Asg_Welcome_Task", [("varTask.Subject", "Assign", R("fxWelcomeSubject")), ("varTask.WhoId", "Assign", R("varContact.Id")),
                                  ("varTask.WhatId", "Assign", R("$Record.Id")), ("varTask.OwnerId", "Assign", R("$Record.OwnerId")),
                                  ("varTask.ActivityDate", "Assign", R("fxDueDate")), ("varTask.Priority", "Assign", "Normal"),
                                  ("varTask.Status", "Assign", "Not Started"), ("colTasks", "Add", R("varTask")), ("varTaskCount", "Add", 1)],
             "Loop_Contacts")
    f.decision("Dec_Any_Contacts", [("Has_Contacts", [("varTaskCount", "GreaterThan", 0)], "Create_Welcome_Tasks")], "Create_Type_Change_Task", "No Contacts")
    f.create("Create_Welcome_Tasks", input_ref="colTasks", nxt="Send_Customer_Email", fault="Log_Fault")
    f.create("Create_Type_Change_Task", "Task", {"Subject": PFX + "Account is now a customer - plan onboarding", "WhatId": R("$Record.Id"),
                                                 "OwnerId": R("$Record.OwnerId"), "Description": R("ttWelcome"), "ActivityDate": R("fxDueDate"),
                                                 "Priority": "Normal", "Status": "Not Started"}, "Send_Customer_Email", "Log_Fault")
    f.email("Send_Customer_Email", R("$User.Email"), PFX + "Account became a customer", R("ttWelcome"), None, "Log_Fault")
    # async path
    f.subflow("Sub_Normalize_Contacts", "AUT_Contact_Data_Normalizer", {"inAccountId": R("$Record.Id")}, {"outUpdatedCount": "varUpdatedContacts"},
              "Sub_Account_Health")
    f.subflow("Sub_Account_Health", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.Id")},
              {"outScore": "varHealthScore", "outRating": "varHealthRating"}, "Dec_Health_Low")
    f.decision("Dec_Health_Low", [("Low_Health", [("varHealthScore", "LessThan", 40)], "Create_Health_Task")], None, "Healthy")
    f.create("Create_Health_Task", "Task", {"Subject": PFX + "New customer with low health score", "WhatId": R("$Record.Id"),
                                            "OwnerId": R("$Record.OwnerId"), "Description": R("ttHealth"), "ActivityDate": R("fxDueDate"),
                                            "Priority": "High", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Previous_Type", obj="Account", trigger="RecordAfterSave", record_trigger="Update",
            filters=[("Type", "EqualTo", "Customer - Direct"), ("Type", "EqualTo", "Customer - Channel")], filter_logic="or", changed=True,
            paths=[{"async": "Sub_Normalize_Contacts"}])
    return f


ALL = [contact_email_change, lead_hot, opp_contact_roles, oli_before_delete, case_email_matcher,
       task_before_save, event_prep, contract_activation, asset_renewal, account_became_customer]

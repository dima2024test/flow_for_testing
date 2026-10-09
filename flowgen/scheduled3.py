from flowlib import Flow, R, D
from common import log_fault, admin_lookup, PFX

START = "2026-10-12"


def asset_warranty():
    f = Flow("SCH_Weekly_Asset_Usage_End_Review", "SCH Weekly Asset Usage End Review", "sch",
             "Weekly, per installed/registered Asset with a usage end date: expired assets get a clean-up Task; assets ending within "
             "30 days get a de-duplicated renewal Task whose priority depends on open High cases on the asset and the account health.")
    f.var("varCase", "SObject", obj="Case")
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varHighCases", "Number", scale=0, default=0)
    f.var("varScore", "Number", scale=0, default=0)
    f.var("varRating", "String", default="n/a")
    f.formula("fxIn30Days", "Date", "TODAY() + 30")
    f.formula("fxPriority", "String", "IF({!varHighCases} > 0, 'High', 'Normal')")
    f.tt("ttRenewal", "Asset {!$Record.Name} reaches its usage end date on {!$Record.UsageEndDate}.\nOpen cases on asset: {!varOpenCases} "
                      "(High: {!varHighCases})\nAccount health score: {!varScore} / rating {!varRating}")
    f.decision("Dec_Usage_Window", [
        ("Expired", [("$Record.UsageEndDate", "LessThan", R("$Flow.CurrentDate"))], "Create_Expired_Task"),
        ("Ending_Soon", [("$Record.UsageEndDate", "LessThanOrEqualTo", R("fxIn30Days"))], "Get_Existing_Renewal_Task")],
        None, "Not Yet")
    f.create("Create_Expired_Task", "Task", {"Subject": PFX + "Asset past usage end - review status", "WhatId": R("$Record.Id"),
                                             "OwnerId": R("$Record.OwnerId"), "Priority": "Low", "Status": "Not Started"}, None, "Log_Fault")
    f.get("Get_Existing_Renewal_Task", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                                ("Subject", "StartsWith", PFX + "Asset renewal")], "Dec_Task_Exists", "Log_Fault", first=True)
    f.decision("Dec_Task_Exists", [("Exists", [("Get_Existing_Renewal_Task", "IsNull", False)], None)], "Get_Asset_Cases", "No Task")
    f.get("Get_Asset_Cases", "Case", [("AssetId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("varOpenCases", "AssignCount", R("Get_Asset_Cases"))], "Loop_Cases")
    f.loop("Loop_Cases", "Get_Asset_Cases", "Dec_High_Case", "Dec_Has_Account", var="varCase")
    f.decision("Dec_High_Case", [("High", [("varCase.Priority", "EqualTo", "High")], "Asg_High_Case")], "Loop_Cases", "Not High")
    f.assign("Asg_High_Case", [("varHighCases", "Add", 1)], "Loop_Cases")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Sub_Account_Health")], "Create_Renewal_Task", "No Account")
    f.subflow("Sub_Account_Health", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.AccountId")},
              {"outScore": "varScore", "outRating": "varRating"}, "Create_Renewal_Task")
    f.create("Create_Renewal_Task", "Task", {"Subject": PFX + "Asset renewal due within 30 days", "WhatId": R("$Record.Id"),
                                             "OwnerId": R("$Record.OwnerId"), "ActivityDate": R("$Record.UsageEndDate"), "Priority": R("fxPriority"),
                                             "Status": "Not Started", "Description": R("ttRenewal")}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Usage_Window", obj="Asset", trigger="Scheduled",
            filters=[("Status", "EqualTo", "Installed"), ("Status", "EqualTo", "Registered"), ("UsageEndDate", "IsNull", False)],
            filter_logic="(1 OR 2) AND 3", schedule=("Weekly", START, "05:15:00.000Z"))
    return f


def meeting_prep():
    f = Flow("SCH_Daily_Customer_Meeting_Prep", "SCH Daily Customer Meeting Prep", "sch",
             "Daily batch (no object): loads Events with a Who starting within 24 hours (soonest 30), skips those already prepared "
             "(one Get of recent prep Tasks + collection filter), bulk-creates prep Tasks, then takes an activity snapshot of the soonest "
             "meeting's contact and e-mails a warning if that contact has overdue tasks.")
    f.var("varEvent", "SObject", obj="Event")
    f.var("varNewTask", "SObject", obj="Task")
    f.var("colNewTasks", "SObject", coll=True, obj="Task")
    f.var("varEventCount", "Number", scale=0, default=0)
    f.var("varExisting", "Number", scale=0, default=0)
    f.var("varCreated", "Number", scale=0, default=0)
    f.var("varSoonestWhoId", "String")
    f.var("varSoonestSubject", "String")
    f.var("varOverdueTasks", "Number", scale=0, default=0)
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varEngagement", "String")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxIn24h", "DateTime", "NOW() + 1")
    f.formula("fxRecentCutoff", "DateTime", "NOW() - 2")
    f.formula("fxPrepSubject", "String", f"LEFT('{PFX}Meeting prep: ' & {{!varEvent.Subject}}, 255)")
    f.formula("fxPrepDescription", "String", "'Meeting starts ' & TEXT({!varEvent.StartDateTime}) & '. Review open cases and tasks of the attendee.'")
    f.formula("fxSoonestIsContact", "Boolean", "LEFT({!varSoonestWhoId}, 3) = '003'")
    f.tt("ttWarning", "Meeting prep run ({!$Flow.CurrentDate}): {!varEventCount} meetings in the next 24h, {!varCreated} prep tasks created.\n"
                      "Soonest new meeting: {!varSoonestSubject}\nContact engagement: {!varEngagement}\n"
                      "Overdue tasks: {!varOverdueTasks}, open cases: {!varOpenCases}")
    f.get("Get_Upcoming_Events", "Event", [("IsChild", "EqualTo", False), ("WhoId", "IsNull", False),
                                           ("StartDateTime", "GreaterThan", R("fxNow")), ("StartDateTime", "LessThanOrEqualTo", R("fxIn24h"))],
          "Asg_Event_Count", "Log_Fault")
    f.assign("Asg_Event_Count", [("varEventCount", "AssignCount", R("Get_Upcoming_Events"))], "Dec_Any_Events")
    f.decision("Dec_Any_Events", [("Has_Events", [("varEventCount", "GreaterThan", 0)], "Get_Recent_Prep_Tasks")], None, "No Meetings")
    f.get("Get_Recent_Prep_Tasks", "Task", [("Subject", "StartsWith", PFX + "Meeting prep"), ("CreatedDate", "GreaterThan", R("fxRecentCutoff"))],
          "Sort_Events", "Log_Fault")
    f.sort_coll("Sort_Events", "Get_Upcoming_Events", "StartDateTime", "Asc", "Loop_Events", limit=30)
    # iterate backwards so the last processed (new) meeting is the soonest one
    f.loop("Loop_Events", "Get_Upcoming_Events", "Filter_Existing_Prep", "Dec_Has_New_Tasks", var="varEvent", order="Desc")
    f.filter_coll("Filter_Existing_Prep", "Get_Recent_Prep_Tasks", "Task",
                  [("WhoId", "EqualTo", R("varEvent.WhoId")), ("Subject", "EqualTo", R("fxPrepSubject"))], "Asg_Existing_Count")
    f.assign("Asg_Existing_Count", [("varExisting", "AssignCount", R("Filter_Existing_Prep"))], "Dec_Already_Prepared")
    f.decision("Dec_Already_Prepared", [("Prepared", [("varExisting", "GreaterThan", 0)], "Loop_Events")], "Asg_Prep_Task", "Not Prepared")
    f.assign("Asg_Prep_Task", [("varNewTask.Subject", "Assign", R("fxPrepSubject")), ("varNewTask.WhoId", "Assign", R("varEvent.WhoId")),
                               ("varNewTask.WhatId", "Assign", R("varEvent.WhatId")), ("varNewTask.OwnerId", "Assign", R("varEvent.OwnerId")),
                               ("varNewTask.ActivityDate", "Assign", R("$Flow.CurrentDate")), ("varNewTask.Priority", "Assign", "Normal"),
                               ("varNewTask.Status", "Assign", "Not Started"), ("varNewTask.Description", "Assign", R("fxPrepDescription")),
                               ("colNewTasks", "Add", R("varNewTask")), ("varCreated", "Add", 1),
                               ("varSoonestWhoId", "Assign", R("varEvent.WhoId")), ("varSoonestSubject", "Assign", R("varEvent.Subject"))], "Loop_Events")
    f.decision("Dec_Has_New_Tasks", [("Has_New", [("varCreated", "GreaterThan", 0)], "Create_Prep_Tasks")], None, "All Prepared")
    f.create("Create_Prep_Tasks", input_ref="colNewTasks", nxt="Dec_Soonest_Is_Contact", fault="Log_Fault")
    f.decision("Dec_Soonest_Is_Contact", [("Is_Contact", [("fxSoonestIsContact", "EqualTo", True)], "Sub_Contact_Snapshot")], None, "Lead")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("varSoonestWhoId")},
              {"outOverdueTasks": "varOverdueTasks", "outOpenCases": "varOpenCases", "outEngagement": "varEngagement"}, "Dec_Has_Overdue")
    f.decision("Dec_Has_Overdue", [("Has_Overdue", [("varOverdueTasks", "GreaterThan", 0)], "Send_Overdue_Warning")], None, "All Current")
    f.email("Send_Overdue_Warning", R("$User.Email"), PFX + "Upcoming meeting contact has overdue tasks", R("ttWarning"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Upcoming_Events", trigger="Scheduled", schedule=("Daily", START, "06:45:00.000Z"))
    return f


def contact_birthday():
    f = Flow("SCH_Daily_Contact_Birthday_Outreach", "SCH Daily Contact Birthday Outreach", "sch",
             "Daily, per Contact with a birthdate: on the birthday, checks (via loop) that no greeting Task was created in the last "
             "300 days, takes an activity snapshot and creates either a greeting Task or a 'resolve open issues first' Task, then e-mails the owner.")
    f.var("varTask", "SObject", obj="Task")
    f.var("varGreeted", "Boolean", default=False)
    f.var("varOverdueTasks", "Number", scale=0, default=0)
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varEngagement", "String")
    f.formula("fxIsBirthday", "Boolean", "AND(MONTH({!$Record.Birthdate}) = MONTH(TODAY()), DAY({!$Record.Birthdate}) = DAY(TODAY()))")
    f.formula("fxCutoff300", "DateTime", "NOW() - 300")
    f.tt("ttOwnerNote", "Today is the birthday of {!$Record.FirstName} {!$Record.LastName}.\nEngagement: {!varEngagement}\n"
                        "Overdue tasks: {!varOverdueTasks}, open cases: {!varOpenCases}.\nA task has been created for you.")
    f.decision("Dec_Is_Birthday", [("Birthday_Today", [("fxIsBirthday", "EqualTo", True)], "Get_Previous_Greetings")], None, "Not Today")
    f.get("Get_Previous_Greetings", "Task", [("WhoId", "EqualTo", R("$Record.Id")), ("Subject", "StartsWith", PFX + "Birthday")],
          "Loop_Greetings", "Log_Fault")
    f.loop("Loop_Greetings", "Get_Previous_Greetings", "Dec_Recent_Greeting", "Dec_Already_Greeted", var="varTask")
    f.decision("Dec_Recent_Greeting", [("Recent", [("varTask.CreatedDate", "GreaterThan", R("fxCutoff300"))], "Asg_Greeted")], "Loop_Greetings", "Older")
    f.assign("Asg_Greeted", [("varGreeted", "Assign", True)], "Loop_Greetings")
    f.decision("Dec_Already_Greeted", [("Greeted", [("varGreeted", "EqualTo", True)], None)], "Sub_Contact_Snapshot", "Not Yet")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("$Record.Id")},
              {"outOverdueTasks": "varOverdueTasks", "outOpenCases": "varOpenCases", "outEngagement": "varEngagement"}, "Dec_Open_Issues")
    f.decision("Dec_Open_Issues", [("Has_Issues", [("varOverdueTasks", "GreaterThan", 0), ("varOpenCases", "GreaterThan", 0)], "Create_Issue_Task", "or")],
               "Create_Greeting_Task", "No Issues")
    f.create("Create_Issue_Task", "Task", {"Subject": PFX + "Birthday - resolve open issues before greeting", "WhoId": R("$Record.Id"),
                                           "OwnerId": R("$Record.OwnerId"), "ActivityDate": R("$Flow.CurrentDate"), "Priority": "High",
                                           "Status": "Not Started", "Description": R("ttOwnerNote")}, "Send_Owner_Note", "Log_Fault")
    f.create("Create_Greeting_Task", "Task", {"Subject": PFX + "Birthday greeting", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                              "ActivityDate": R("$Flow.CurrentDate"), "Priority": "Normal", "Status": "Not Started",
                                              "Description": R("ttOwnerNote")}, "Send_Owner_Note", "Log_Fault")
    f.email("Send_Owner_Note", R("$Record.Owner.Email"), PFX + "Contact birthday today", R("ttOwnerNote"), None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Is_Birthday", obj="Contact", trigger="Scheduled", filters=[("Birthdate", "IsNull", False), ("HasOptedOutOfEmail", "EqualTo", False)],
            schedule=("Daily", START, "07:30:00.000Z"))
    return f


def opp_products():
    f = Flow("SCH_Weekly_Opportunity_Product_Check", "SCH Weekly Opportunity Product Check", "sch",
             "Weekly, per Qualification/Needs Analysis Opportunity: deals without products get a de-duplicated Task; otherwise line items "
             "are totalled, discounts over 20% trigger a review Task, and NextStep is updated with product and account pipeline totals.")
    f.var("varItem", "SObject", obj="OpportunityLineItem")
    f.var("varItemCount", "Number", scale=0, default=0)
    f.var("varUnits", "Number", scale=2, default=0)
    f.var("varLineTotal", "Currency", scale=2, default=0)
    f.var("varDiscounted", "Number", scale=0, default=0)
    f.var("varAccountPipeline", "Currency", scale=2, default=0)
    f.formula("fxLineTotal", "Currency", "BLANKVALUE({!varItem.TotalPrice}, 0)", scale=2)
    f.formula("fxQty", "Number", "BLANKVALUE({!varItem.Quantity}, 0)", scale=2)
    f.formula("fxNextStep", "String", "LEFT('Products: ' & TEXT({!varUnits}) & ' units / ' & TEXT({!varLineTotal}) & '; account pipeline ' & "
                                      "TEXT({!varAccountPipeline}), 255)")
    f.get("Get_Line_Items", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("$Record.Id"))], "Asg_Item_Count", "Log_Fault")
    f.assign("Asg_Item_Count", [("varItemCount", "AssignCount", R("Get_Line_Items"))], "Dec_Has_Items")
    f.decision("Dec_Has_Items", [("Has_Items", [("varItemCount", "GreaterThan", 0)], "Loop_Items")], "Get_Existing_Gap_Task", "No Products")
    f.get("Get_Existing_Gap_Task", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                            ("Subject", "EqualTo", PFX + "Add products to opportunity")], "Dec_Gap_Task_Exists", "Log_Fault", first=True)
    f.decision("Dec_Gap_Task_Exists", [("Exists", [("Get_Existing_Gap_Task", "IsNull", False)], None)], "Create_No_Products_Task", "No Task")
    f.create("Create_No_Products_Task", "Task", {"Subject": PFX + "Add products to opportunity", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                                 "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    f.loop("Loop_Items", "Get_Line_Items", "Asg_Totals", "Filter_High_Discount", var="varItem")
    f.assign("Asg_Totals", [("varLineTotal", "Add", R("fxLineTotal")), ("varUnits", "Add", R("fxQty"))], "Loop_Items")
    f.filter_coll("Filter_High_Discount", "Get_Line_Items", "OpportunityLineItem", [("Discount", "GreaterThan", 20)], "Asg_Discount_Count")
    f.assign("Asg_Discount_Count", [("varDiscounted", "AssignCount", R("Filter_High_Discount"))], "Dec_Discount_Review")
    f.decision("Dec_Discount_Review", [("Needs_Review", [("varDiscounted", "GreaterThan", 0)], "Create_Discount_Task")], "Dec_Has_Account", "Normal Pricing")
    f.create("Create_Discount_Task", "Task", {"Subject": PFX + "Review line item discounts over 20%", "WhatId": R("$Record.Id"),
                                              "OwnerId": R("$Record.OwnerId"), "Priority": "High", "Status": "Not Started"}, "Dec_Has_Account", "Log_Fault")
    f.decision("Dec_Has_Account", [("Has_Account", [("$Record.AccountId", "IsNull", False)], "Sub_Pipeline_Summary")], "Update_Next_Step", "No Account")
    f.subflow("Sub_Pipeline_Summary", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("$Record.AccountId"), "inCreateTask": False},
              {"outTotalPipeline": "varAccountPipeline"}, "Update_Next_Step")
    f.update("Update_Next_Step", "Opportunity", [("Id", "EqualTo", R("$Record.Id"))], {"NextStep": R("fxNextStep")}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Get_Line_Items", obj="Opportunity", trigger="Scheduled",
            filters=[("StageName", "EqualTo", "Qualification"), ("StageName", "EqualTo", "Needs Analysis")], filter_logic="or",
            schedule=("Weekly", START, "09:00:00.000Z"))
    return f


def working_case_followup():
    f = Flow("SCH_Daily_Idle_Working_Case_Followup", "SCH Daily Idle Working Case Followup", "sch",
             "Daily, per Case in status Working untouched for 5 days: without open tasks a follow-up Task is created (with contact "
             "snapshot); with open tasks, overdue ones are bulk-raised to High and the case priority is raised.")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varTaskCount", "Number", scale=0, default=0)
    f.var("varBumped", "Number", scale=0, default=0)
    f.var("varEngagement", "String", default="unknown")
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.formula("fxIdleCutoff", "DateTime", "NOW() - 5")
    f.formula("fxDue", "Date", "TODAY() + 1")
    f.tt("ttFollowup", "Case {!$Record.CaseNumber} has been in Working without changes for 5+ days and has no open tasks.\n"
                       "Contact engagement: {!varEngagement} (open cases for contact: {!varOpenCases})")
    f.decision("Dec_Idle", [("Idle", [("$Record.LastModifiedDate", "LessThan", R("fxIdleCutoff"))], "Get_Case_Tasks")], None, "Recently Updated")
    f.get("Get_Case_Tasks", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Asg_Task_Count", "Log_Fault")
    f.assign("Asg_Task_Count", [("varTaskCount", "AssignCount", R("Get_Case_Tasks"))], "Dec_Has_Tasks")
    f.decision("Dec_Has_Tasks", [("Has_Tasks", [("varTaskCount", "GreaterThan", 0)], "Loop_Tasks")], "Dec_Has_Contact", "No Open Tasks")
    f.decision("Dec_Has_Contact", [("Has_Contact", [("$Record.ContactId", "IsNull", False)], "Sub_Contact_Snapshot")], "Create_Followup_Task", "No Contact")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("$Record.ContactId")},
              {"outEngagement": "varEngagement", "outOpenCases": "varOpenCases"}, "Create_Followup_Task")
    f.create("Create_Followup_Task", "Task", {"Subject": PFX + "Idle case - contact customer", "WhatId": R("$Record.Id"), "WhoId": R("$Record.ContactId"),
                                              "OwnerId": R("$Record.CreatedById"), "ActivityDate": R("fxDue"), "Priority": "Normal",
                                              "Status": "Not Started", "Description": R("ttFollowup")}, None, "Log_Fault")
    f.loop("Loop_Tasks", "Get_Case_Tasks", "Dec_Task_Overdue", "Dec_Any_Bumped", var="varTask")
    f.decision("Dec_Task_Overdue", [("Overdue", [("varTask.ActivityDate", "LessThan", R("$Flow.CurrentDate")),
                                                 ("varTask.Priority", "NotEqualTo", "High")], "Asg_Bump")], "Loop_Tasks", "On Time")
    f.assign("Asg_Bump", [("varTask.Priority", "Assign", "High"), ("colTasksToUpdate", "Add", R("varTask")), ("varBumped", "Add", 1)], "Loop_Tasks")
    f.decision("Dec_Any_Bumped", [("Bumped", [("varBumped", "GreaterThan", 0)], "Update_Tasks")], None, "Nothing Overdue")
    f.update("Update_Tasks", input_ref="colTasksToUpdate", nxt="Update_Case_Priority", fault="Log_Fault")
    f.update("Update_Case_Priority", "Case", [("Id", "EqualTo", R("$Record.Id"))], {"Priority": "High"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Idle", obj="Case", trigger="Scheduled", filters=[("Status", "EqualTo", "Working")],
            schedule=("Daily", START, "08:15:00.000Z"))
    return f


def inactive_user_handover():
    f = Flow("SCH_Weekly_Inactive_User_Handover", "SCH Weekly Inactive User Handover", "sch",
             "Weekly batch (no object): finds Standard Users deactivated (modified) in the last 7 days (max 20 per run), moves each user's "
             "open Tasks to the first System Administrator via subflow, reassigns their open Opportunities, and records/e-mails a summary.")
    f.var("varUser", "SObject", obj="User")
    f.var("varUserCount", "Number", scale=0, default=0)
    f.var("varProcessed", "Number", scale=0, default=0)
    f.var("varMoved", "Number", scale=0, default=0)
    f.var("varTotalMoved", "Number", scale=0, default=0)
    f.var("varMoveResult", "String")
    f.var("varUserList", "String", default="")
    f.formula("fxCutoff7", "DateTime", "NOW() - 7")
    f.formula("fxUserLine", "String", "{!varUser.Name} & ': ' & TEXT({!varMoved}) & ' task(s); '")
    f.tt("ttHandover", "Deactivated user handover ({!$Flow.CurrentDate})\nUsers processed: {!varProcessed} of {!varUserCount}\n"
                       "Open tasks moved: {!varTotalMoved}\nOpen opportunities of these users were reassigned to you.\n\n{!varUserList}")
    admin_lookup(f, "Dec_Admin_Found", "Log_Fault")
    f.decision("Dec_Admin_Found", [("Found", [("Get_Admin_User", "IsNull", False)], "Get_Inactive_Users")], None, "No Admin")
    f.get("Get_Inactive_Users", "User", [("IsActive", "EqualTo", False), ("UserType", "EqualTo", "Standard"),
                                         ("LastModifiedDate", "GreaterThan", R("fxCutoff7"))], "Asg_User_Count", "Log_Fault")
    f.assign("Asg_User_Count", [("varUserCount", "AssignCount", R("Get_Inactive_Users"))], "Dec_Any_Users")
    f.decision("Dec_Any_Users", [("Has_Users", [("varUserCount", "GreaterThan", 0)], "Sort_Users")], None, "No Deactivations")
    f.sort_coll("Sort_Users", "Get_Inactive_Users", "LastModifiedDate", "Desc", "Loop_Users", limit=20)
    f.loop("Loop_Users", "Get_Inactive_Users", "Sub_Reassign_Tasks", "Dec_Anything_Processed", var="varUser")
    f.subflow("Sub_Reassign_Tasks", "AUT_Task_Bulk_Reassign", {"inFromUserId": R("varUser.Id"), "inToUserId": R("Get_Admin_User.Id"), "inHighOnly": False},
              {"outMovedCount": "varMoved", "outResult": "varMoveResult"}, "Update_User_Opportunities")
    f.update("Update_User_Opportunities", "Opportunity", [("OwnerId", "EqualTo", R("varUser.Id")), ("IsClosed", "EqualTo", False)],
             {"OwnerId": R("Get_Admin_User.Id")}, "Asg_Tally", "Log_Fault")
    f.assign("Asg_Tally", [("varTotalMoved", "Add", R("varMoved")), ("varProcessed", "Add", 1), ("varUserList", "Add", R("fxUserLine"))], "Loop_Users")
    f.decision("Dec_Anything_Processed", [("Processed", [("varProcessed", "GreaterThan", 0)], "Create_Handover_Task")], None, "Nothing")
    f.create("Create_Handover_Task", "Task", {"Subject": PFX + "Review handover from deactivated users", "OwnerId": R("Get_Admin_User.Id"),
                                              "ActivityDate": R("$Flow.CurrentDate"), "Priority": "High", "Status": "Not Started",
                                              "Description": R("ttHandover")}, "Send_Handover_Email", "Log_Fault")
    f.email("Send_Handover_Email", R("Get_Admin_User.Email"), PFX + "Deactivated user handover", R("ttHandover"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Admin_Profile", trigger="Scheduled", schedule=("Weekly", START, "23:30:00.000Z"))
    return f


def product_audit():
    f = Flow("SCH_Weekly_Product_Catalog_Audit", "SCH Weekly Product Catalog Audit", "sch",
             "Weekly batch (no object): checks all active Products for missing product code or family, counts products added in the "
             "last 30 days, stores an audit Task (High if gaps found) and e-mails the report.")
    f.var("varProduct", "SObject", obj="Product2")
    f.var("varActive", "Number", scale=0, default=0)
    f.var("varMissingCode", "Number", scale=0, default=0)
    f.var("varMissingFamily", "Number", scale=0, default=0)
    f.var("varNewProducts", "Number", scale=0, default=0)
    f.var("varGapList", "String", default="")
    f.formula("fxCutoff30", "DateTime", "NOW() - 30")
    f.formula("fxGapLine", "String", "LEFT({!varProduct.Name}, 60) & '; '")
    f.formula("fxPriority", "String", "IF({!varMissingCode} + {!varMissingFamily} > 0, 'High', 'Low')")
    f.tt("ttAudit", "Product catalog audit ({!$Flow.CurrentDate})\nActive products: {!varActive}\nMissing product code: {!varMissingCode}\n"
                    "Missing family: {!varMissingFamily}\nAdded in last 30 days: {!varNewProducts}\n\nProducts with gaps:\n{!varGapList}")
    f.get("Get_Active_Products", "Product2", [("IsActive", "EqualTo", True)], "Asg_Active_Count", "Log_Fault", sort="Name")
    f.assign("Asg_Active_Count", [("varActive", "AssignCount", R("Get_Active_Products"))], "Dec_Any_Products")
    f.decision("Dec_Any_Products", [("Has_Products", [("varActive", "GreaterThan", 0)], "Loop_Products")], "Create_Audit_Task", "Empty Catalog")
    f.loop("Loop_Products", "Get_Active_Products", "Dec_Data_Gap", "Filter_New_Products", var="varProduct")
    f.decision("Dec_Data_Gap", [
        ("Missing_Code", [("varProduct.ProductCode", "IsNull", True)], "Asg_Missing_Code"),
        ("Missing_Family", [("varProduct.Family", "IsNull", True)], "Asg_Missing_Family")], "Loop_Products", "Complete")
    f.assign("Asg_Missing_Code", [("varMissingCode", "Add", 1), ("varGapList", "Add", R("fxGapLine"))], "Loop_Products")
    f.assign("Asg_Missing_Family", [("varMissingFamily", "Add", 1), ("varGapList", "Add", R("fxGapLine"))], "Loop_Products")
    f.filter_coll("Filter_New_Products", "Get_Active_Products", "Product2", [("CreatedDate", "GreaterThan", R("fxCutoff30"))], "Asg_New_Count")
    f.assign("Asg_New_Count", [("varNewProducts", "AssignCount", R("Filter_New_Products"))], "Create_Audit_Task")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Weekly product catalog audit", "Description": R("ttAudit"), "Priority": R("fxPriority"),
                                           "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Dec_Gaps_Found", "Log_Fault")
    f.decision("Dec_Gaps_Found", [("Gaps", [("varMissingCode", "GreaterThan", 0), ("varMissingFamily", "GreaterThan", 0)], "Send_Audit_Email", "or")],
               None, "Catalog Clean")
    f.email("Send_Audit_Email", R("$User.Email"), PFX + "Product catalog gaps found", R("ttAudit"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Active_Products", trigger="Scheduled", schedule=("Weekly", START, "02:15:00.000Z"))
    return f


def lead_source_report():
    f = Flow("SCH_Weekly_New_Lead_Source_Report", "SCH Weekly New Lead Source Report", "sch",
             "Weekly batch (no object): counts unconverted leads created in the last 7 days per lead source, bulk-creates call Tasks for "
             "hot, not-yet-contacted leads, stores the report as a Task and e-mails it.")
    f.var("varLead", "SObject", obj="Lead")
    f.var("varHotLead", "SObject", obj="Lead")
    f.var("varNewTask", "SObject", obj="Task")
    f.var("colNewTasks", "SObject", coll=True, obj="Task")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varWeb", "Number", scale=0, default=0)
    f.var("varPhone", "Number", scale=0, default=0)
    f.var("varPartner", "Number", scale=0, default=0)
    f.var("varOther", "Number", scale=0, default=0)
    f.var("varHot", "Number", scale=0, default=0)
    f.formula("fxCutoff7", "DateTime", "NOW() - 7")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.tt("ttReport", "New leads last 7 days ({!$Flow.CurrentDate}): {!varTotal}\nWeb: {!varWeb}\nPhone Inquiry: {!varPhone}\n"
                     "Partner Referral: {!varPartner}\nOther / blank: {!varOther}\nHot uncontacted leads with new call task: {!varHot}")
    f.get("Get_New_Leads", "Lead", [("IsConverted", "EqualTo", False), ("CreatedDate", "GreaterThan", R("fxCutoff7"))], "Asg_Total", "Log_Fault")
    f.assign("Asg_Total", [("varTotal", "AssignCount", R("Get_New_Leads"))], "Dec_Any_Leads")
    f.decision("Dec_Any_Leads", [("Has_Leads", [("varTotal", "GreaterThan", 0)], "Loop_Leads")], "Create_Report_Task", "No New Leads")
    f.loop("Loop_Leads", "Get_New_Leads", "Dec_Source", "Filter_Hot_Uncontacted", var="varLead")
    f.decision("Dec_Source", [
        ("Web", [("varLead.LeadSource", "EqualTo", "Web")], "Asg_Web"),
        ("Phone", [("varLead.LeadSource", "EqualTo", "Phone Inquiry")], "Asg_Phone"),
        ("Partner", [("varLead.LeadSource", "EqualTo", "Partner Referral")], "Asg_Partner")], "Asg_Other", "Other Source")
    f.assign("Asg_Web", [("varWeb", "Add", 1)], "Loop_Leads")
    f.assign("Asg_Phone", [("varPhone", "Add", 1)], "Loop_Leads")
    f.assign("Asg_Partner", [("varPartner", "Add", 1)], "Loop_Leads")
    f.assign("Asg_Other", [("varOther", "Add", 1)], "Loop_Leads")
    f.filter_coll("Filter_Hot_Uncontacted", "Get_New_Leads", "Lead", [("Rating", "EqualTo", "Hot"), ("Status", "EqualTo", "Open - Not Contacted")],
                  "Loop_Hot_Leads")
    f.loop("Loop_Hot_Leads", "Filter_Hot_Uncontacted", "Asg_Call_Task", "Dec_Has_Hot", var="varHotLead")
    f.assign("Asg_Call_Task", [("varNewTask.Subject", "Assign", PFX + "Call hot new lead"), ("varNewTask.WhoId", "Assign", R("varHotLead.Id")),
                               ("varNewTask.OwnerId", "Assign", R("varHotLead.CreatedById")), ("varNewTask.ActivityDate", "Assign", R("fxTomorrow")),
                               ("varNewTask.Priority", "Assign", "High"), ("varNewTask.Status", "Assign", "Not Started"),
                               ("colNewTasks", "Add", R("varNewTask")), ("varHot", "Add", 1)], "Loop_Hot_Leads")
    f.decision("Dec_Has_Hot", [("Has_Hot", [("varHot", "GreaterThan", 0)], "Create_Call_Tasks")], "Create_Report_Task", "No Hot Leads")
    f.create("Create_Call_Tasks", input_ref="colNewTasks", nxt="Create_Report_Task", fault="Log_Fault")
    f.create("Create_Report_Task", "Task", {"Subject": PFX + "Weekly new lead source report", "Description": R("ttReport"), "Priority": "Low",
                                            "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Report_Email", "Log_Fault")
    f.email("Send_Report_Email", R("$User.Email"), PFX + "Weekly new lead source report", R("ttReport"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_New_Leads", trigger="Scheduled", schedule=("Weekly", START, "10:30:00.000Z"))
    return f


def draft_contracts():
    f = Flow("SCH_Once_Stale_Draft_Contract_Review", "SCH Once Stale Draft Contract Review", "sch",
             "One-time batch (no object): finds Draft contracts older than 60 days, bulk-creates review Tasks for those whose start date "
             "has already passed, counts the rest as pending, and stores/e-mails a summary.")
    f.var("varContract", "SObject", obj="Contract")
    f.var("varNewTask", "SObject", obj="Task")
    f.var("colNewTasks", "SObject", coll=True, obj="Task")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varPastStart", "Number", scale=0, default=0)
    f.var("varPending", "Number", scale=0, default=0)
    f.formula("fxCutoff60", "DateTime", "NOW() - 60")
    f.formula("fxDue", "Date", "TODAY() + 7")
    f.tt("ttSummary", "Stale draft contract review ({!$Flow.CurrentDate})\nDraft contracts older than 60 days: {!varTotal}\n"
                      "Start date already passed (review task created): {!varPastStart}\nStart date still ahead: {!varPending}")
    f.get("Get_Draft_Contracts", "Contract", [("Status", "EqualTo", "Draft"), ("CreatedDate", "LessThan", R("fxCutoff60"))], "Asg_Total", "Log_Fault",
          sort="StartDate")
    f.assign("Asg_Total", [("varTotal", "AssignCount", R("Get_Draft_Contracts"))], "Dec_Any_Drafts")
    f.decision("Dec_Any_Drafts", [("Has_Drafts", [("varTotal", "GreaterThan", 0)], "Loop_Contracts")], "Create_Summary_Task", "No Drafts")
    f.loop("Loop_Contracts", "Get_Draft_Contracts", "Dec_Start_Passed", "Dec_Has_Review_Tasks", var="varContract")
    f.decision("Dec_Start_Passed", [("Start_Passed", [("varContract.StartDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Review_Task")],
               "Asg_Pending", "Start Ahead")
    f.assign("Asg_Review_Task", [("varNewTask.Subject", "Assign", PFX + "Draft contract past start date - activate or cancel"),
                                 ("varNewTask.WhatId", "Assign", R("varContract.Id")), ("varNewTask.OwnerId", "Assign", R("varContract.OwnerId")),
                                 ("varNewTask.ActivityDate", "Assign", R("fxDue")), ("varNewTask.Priority", "Assign", "Normal"),
                                 ("varNewTask.Status", "Assign", "Not Started"), ("colNewTasks", "Add", R("varNewTask")),
                                 ("varPastStart", "Add", 1)], "Loop_Contracts")
    f.assign("Asg_Pending", [("varPending", "Add", 1)], "Loop_Contracts")
    f.decision("Dec_Has_Review_Tasks", [("Has_Tasks", [("varPastStart", "GreaterThan", 0)], "Create_Review_Tasks")], "Create_Summary_Task", "None")
    f.create("Create_Review_Tasks", input_ref="colNewTasks", nxt="Create_Summary_Task", fault="Log_Fault")
    f.create("Create_Summary_Task", "Task", {"Subject": PFX + "Stale draft contract review", "Description": R("ttSummary"), "Priority": "Low",
                                             "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Summary_Email", "Log_Fault")
    f.email("Send_Summary_Email", R("$User.Email"), PFX + "Stale draft contract review", R("ttSummary"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Draft_Contracts", trigger="Scheduled", schedule=("Once", START, "11:00:00.000Z"))
    return f


def orphan_task_linker():
    f = Flow("SCH_Daily_Orphan_Task_Account_Linker", "SCH Daily Orphan Task Account Linker", "sch",
             "Daily batch (no object): takes up to 50 newest open Tasks that have a Who but no What, looks up the Contact and links the "
             "task to the contact's Account in one bulk update; leads/contacts without account are skipped; summary is e-mailed.")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varLinked", "Number", scale=0, default=0)
    f.var("varSkipped", "Number", scale=0, default=0)
    f.tt("ttSummary", "Orphan task linker ({!$Flow.CurrentDate})\nOpen tasks without related record: {!varTotal}\n"
                      "Linked to contact's account (max 50 per run): {!varLinked}\nSkipped (lead or no account): {!varSkipped}")
    f.get("Get_Orphan_Tasks", "Task", [("IsClosed", "EqualTo", False), ("WhatId", "IsNull", True), ("WhoId", "IsNull", False)], "Asg_Total", "Log_Fault")
    f.assign("Asg_Total", [("varTotal", "AssignCount", R("Get_Orphan_Tasks"))], "Dec_Any_Orphans")
    f.decision("Dec_Any_Orphans", [("Has_Orphans", [("varTotal", "GreaterThan", 0)], "Sort_Newest_First")], None, "None Found")
    f.sort_coll("Sort_Newest_First", "Get_Orphan_Tasks", "CreatedDate", "Desc", "Loop_Tasks", limit=50)
    f.loop("Loop_Tasks", "Get_Orphan_Tasks", "Get_Who_Contact", "Dec_Has_Links", var="varTask")
    f.get("Get_Who_Contact", "Contact", [("Id", "EqualTo", R("varTask.WhoId"))], "Dec_Contact_Has_Account", "Log_Fault", first=True)
    f.decision("Dec_Contact_Has_Account", [("Linkable", [("Get_Who_Contact", "IsNull", False), ("Get_Who_Contact.Id", "EqualTo", R("varTask.WhoId")),
                                                   ("Get_Who_Contact.AccountId", "IsNull", False)], "Asg_Link")],
               "Asg_Skip", "Not Linkable")
    f.assign("Asg_Link", [("varTask.WhatId", "Assign", R("Get_Who_Contact.AccountId")), ("colTasksToUpdate", "Add", R("varTask")),
                          ("varLinked", "Add", 1)], "Loop_Tasks")
    f.assign("Asg_Skip", [("varSkipped", "Add", 1)], "Loop_Tasks")
    f.decision("Dec_Has_Links", [("Has_Links", [("varLinked", "GreaterThan", 0)], "Update_Tasks")], "Create_Summary_Task", "Nothing Linked")
    f.update("Update_Tasks", input_ref="colTasksToUpdate", nxt="Create_Summary_Task", fault="Log_Fault")
    f.create("Create_Summary_Task", "Task", {"Subject": PFX + "Orphan task linker summary", "Description": R("ttSummary"), "Priority": "Low",
                                             "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Summary_Email", "Log_Fault")
    f.email("Send_Summary_Email", R("$User.Email"), PFX + "Orphan task linker summary", R("ttSummary"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Orphan_Tasks", trigger="Scheduled", schedule=("Daily", START, "03:45:00.000Z"))
    return f


ALL = [asset_warranty, meeting_prep, contact_birthday, opp_products, working_case_followup, inactive_user_handover,
       product_audit, lead_source_report, draft_contracts, orphan_task_linker]

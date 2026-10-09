from flowlib import Flow, R, D
from common import log_fault, PFX

START = "2026-10-12"


def stale_opps():
    f = Flow("SCH_Daily_Stale_Opportunity_Review", "SCH Daily Stale Opportunity Review", "sch",
             "Daily, per open Opportunity: flags past-due or stale (30+ days untouched) deals, de-duplicates reminders, finds the primary "
             "contact and creates a reminder Task; large deals get NextStep updated.")
    f.var("varReason", "String")
    f.var("varPrimaryContactId", "String")
    f.formula("fxStaleCutoff", "DateTime", "NOW() - 30")
    f.formula("fxSubject", "String", f"'{PFX}Stale deal: ' & {{!varReason}}")
    f.formula("fxDueDate", "Date", "TODAY() + 2")
    f.decision("Dec_Deal_Health", [
        ("Past_Due", [("$Record.CloseDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Reason_Past_Due"),
        ("Stale", [("$Record.LastModifiedDate", "LessThan", R("fxStaleCutoff"))], "Asg_Reason_Stale")],
        None, "Healthy")
    f.assign("Asg_Reason_Past_Due", [("varReason", "Assign", "close date in the past")], "Get_Existing_Reminder")
    f.assign("Asg_Reason_Stale", [("varReason", "Assign", "no activity for 30 days")], "Get_Existing_Reminder")
    f.get("Get_Existing_Reminder", "Task", [("WhatId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False),
                                            ("Subject", "StartsWith", PFX + "Stale deal")], "Dec_Reminder_Exists", "Log_Fault", first=True)
    f.decision("Dec_Reminder_Exists", [("Already_Reminded", [("Get_Existing_Reminder", "IsNull", False)], "Asg_Skip")], "Get_Contact_Roles", "No Reminder")
    f.get("Get_Contact_Roles", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("$Record.Id"))], "Loop_Contact_Roles", "Log_Fault")
    f.loop("Loop_Contact_Roles", "Get_Contact_Roles", "Dec_Is_Primary", "Create_Reminder_Task")
    f.decision("Dec_Is_Primary", [("Primary", [("Loop_Contact_Roles.IsPrimary", "EqualTo", True)], "Asg_Primary_Contact")], "Loop_Contact_Roles", "Not Primary")
    f.assign("Asg_Primary_Contact", [("varPrimaryContactId", "Assign", R("Loop_Contact_Roles.ContactId"))], "Loop_Contact_Roles")
    f.create("Create_Reminder_Task", "Task", {"Subject": R("fxSubject"), "WhatId": R("$Record.Id"), "WhoId": R("varPrimaryContactId"),
                                              "OwnerId": R("$Record.OwnerId"), "ActivityDate": R("fxDueDate"), "Priority": "Normal", "Status": "Not Started"},
             "Dec_Large_Deal", "Log_Fault")
    f.decision("Dec_Large_Deal", [("Large_Deal", [("$Record.Amount", "GreaterThanOrEqualTo", 100000)], "Update_Next_Step")], None, "Regular Deal")
    f.update("Update_Next_Step", "Opportunity", [("Id", "EqualTo", R("$Record.Id"))], {"NextStep": "Review close date (flagged by flow)"}, None, "Log_Fault")
    f.assign("Asg_Skip", [("varReason", "Assign", "skipped")])
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Deal_Health", obj="Opportunity", trigger="Scheduled", filters=[("IsClosed", "EqualTo", False)],
            schedule=("Daily", START, "05:00:00.000Z"))
    return f


def weekly_health():
    f = Flow("SCH_Weekly_Account_Health_Batch", "SCH Weekly Account Health Batch", "sch",
             "Weekly, per typed Account: recalculates health via subflow, reacts to rating downgrades (risk Task) and upgrades "
             "(de-duplicated upsell Opportunity), and flags accounts with 3+ open cases older than 14 days.")
    f.var("varPreviousRating", "String")
    f.var("varNewRating", "String")
    f.var("varScore", "Number", scale=0)
    f.var("varOldCaseCount", "Number", scale=0, default=0)
    f.formula("fxCaseCutoff", "DateTime", "NOW() - 14")
    f.formula("fxCloseDate", "Date", "TODAY() + 60")
    f.formula("fxUpsellName", "String", f"LEFT('{PFX}Upsell - ' & {{!$Record.Name}}, 120)")
    f.assign("Asg_Previous_Rating", [("varPreviousRating", "Assign", R("$Record.Rating"))], "Sub_Calculate_Health")
    f.subflow("Sub_Calculate_Health", "AUT_Account_Health_Calculator", {"inAccountId": R("$Record.Id")},
              {"outScore": "varScore", "outRating": "varNewRating"}, "Dec_Rating_Shift")
    f.decision("Dec_Rating_Shift", [
        ("Downgraded", [("varPreviousRating", "EqualTo", "Hot"), ("varNewRating", "NotEqualTo", "Hot")], "Create_Risk_Task"),
        ("Upgraded", [("varNewRating", "EqualTo", "Hot"), ("varPreviousRating", "NotEqualTo", "Hot")], "Get_Existing_Upsell")],
        "Get_Open_Cases", "No Change")
    f.create("Create_Risk_Task", "Task", {"Subject": PFX + "Account health dropped", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                          "Priority": "High", "Status": "Not Started"}, "Get_Open_Cases", "Log_Fault")
    f.get("Get_Existing_Upsell", "Opportunity", [("AccountId", "EqualTo", R("$Record.Id")), ("Name", "StartsWith", PFX + "Upsell"), ("IsClosed", "EqualTo", False)],
          "Dec_Upsell_Exists", "Log_Fault", first=True)
    f.decision("Dec_Upsell_Exists", [("Upsell_Exists", [("Get_Existing_Upsell", "IsNull", False)], "Get_Open_Cases")], "Create_Upsell_Opportunity", "None Yet")
    f.create("Create_Upsell_Opportunity", "Opportunity", {"Name": R("fxUpsellName"), "AccountId": R("$Record.Id"), "StageName": "Prospecting",
                                                          "CloseDate": R("fxCloseDate"), "OwnerId": R("$Record.OwnerId")}, "Get_Open_Cases", "Log_Fault")
    f.get("Get_Open_Cases", "Case", [("AccountId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False)], "Filter_Old_Cases", "Log_Fault")
    f.filter_coll("Filter_Old_Cases", "Get_Open_Cases", "Case", [("CreatedDate", "LessThan", R("fxCaseCutoff"))], "Asg_Old_Case_Count")
    f.assign("Asg_Old_Case_Count", [("varOldCaseCount", "AssignCount", R("Filter_Old_Cases"))], "Dec_Too_Many_Old_Cases")
    f.decision("Dec_Too_Many_Old_Cases", [("Too_Many", [("varOldCaseCount", "GreaterThanOrEqualTo", 3)], "Create_Case_Review_Task")], None, "OK")
    f.create("Create_Case_Review_Task", "Task", {"Subject": PFX + "Review aging support cases", "WhatId": R("$Record.Id"), "OwnerId": R("$Record.OwnerId"),
                                                 "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Asg_Previous_Rating", obj="Account", trigger="Scheduled", filters=[("Type", "IsNull", False)],
            schedule=("Weekly", START, "03:00:00.000Z"))
    return f


def case_aging():
    f = Flow("SCH_Nightly_Case_Aging_Report", "SCH Nightly Case Aging Report", "sch",
             "Nightly batch (no object): loads open cases older than 7 days, sorts by age, buckets 7-30 / 30+ days, raises priority of "
             "30+ day cases, then creates a summary Task and e-mails the report.")
    f.var("varCase", "SObject", obj="Case")
    f.var("colCasesToUpdate", "SObject", coll=True, obj="Case")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varOver30", "Number", scale=0, default=0)
    f.var("varOver7", "Number", scale=0, default=0)
    f.var("varRaised", "Number", scale=0, default=0)
    f.formula("fxCutoff7", "DateTime", "NOW() - 7")
    f.formula("fxCutoff30", "DateTime", "NOW() - 30")
    f.tt("ttReport", "Nightly case aging report ({!$Flow.CurrentDate})\nOpen cases older than 7 days: {!varTotal}\n"
                     "7-30 days: {!varOver7}\n30+ days: {!varOver30}\nPriority raised to High: {!varRaised}")
    f.get("Get_Aging_Cases", "Case", [("IsClosed", "EqualTo", False), ("CreatedDate", "LessThan", R("fxCutoff7"))], "Asg_Total", "Log_Fault")
    f.assign("Asg_Total", [("varTotal", "AssignCount", R("Get_Aging_Cases"))], "Dec_Any_Cases")
    f.decision("Dec_Any_Cases", [("Has_Cases", [("varTotal", "GreaterThan", 0)], "Sort_By_Age")], "Create_Summary_Task", "No Cases")
    f.sort_coll("Sort_By_Age", "Get_Aging_Cases", "CreatedDate", "Asc", "Loop_Cases", limit=200)
    f.loop("Loop_Cases", "Get_Aging_Cases", "Dec_Age_Bucket", "Dec_Has_Updates", var="varCase")
    f.decision("Dec_Age_Bucket", [("Over_30_Days", [("varCase.CreatedDate", "LessThan", R("fxCutoff30"))], "Dec_Already_High")], "Asg_Bucket_7", "7 to 30 Days")
    f.decision("Dec_Already_High", [("Is_High", [("varCase.Priority", "EqualTo", "High")], "Asg_Bucket_30")], "Asg_Raise_Priority", "Not High")
    f.assign("Asg_Raise_Priority", [("varCase.Priority", "Assign", "High"), ("colCasesToUpdate", "Add", R("varCase")), ("varRaised", "Add", 1)], "Asg_Bucket_30")
    f.assign("Asg_Bucket_30", [("varOver30", "Add", 1)], "Loop_Cases")
    f.assign("Asg_Bucket_7", [("varOver7", "Add", 1)], "Loop_Cases")
    f.decision("Dec_Has_Updates", [("Has_Updates", [("varRaised", "GreaterThan", 0)], "Update_Cases")], "Create_Summary_Task", "Nothing To Update")
    f.update("Update_Cases", input_ref="colCasesToUpdate", nxt="Create_Summary_Task", fault="Log_Fault")
    f.create("Create_Summary_Task", "Task", {"Subject": PFX + "Nightly case aging report", "Description": R("ttReport"), "ActivityDate": R("$Flow.CurrentDate"),
                                             "Priority": "Normal", "Status": "Completed"}, "Send_Summary_Email", "Log_Fault")
    f.email("Send_Summary_Email", R("$User.Email"), PFX + "Nightly case aging report", R("ttReport"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Aging_Cases", trigger="Scheduled", schedule=("Daily", START, "01:00:00.000Z"))
    return f


def lead_followup():
    f = Flow("SCH_Daily_Lead_Followup", "SCH Daily Lead Followup", "sch",
             "Daily, per uncontacted Lead: 30+ day leads are closed if a matching Contact exists or set Cold otherwise; 3+ day leads get "
             "a follow-up Task unless one is already open.")
    f.var("varOpenFollowups", "Number", scale=0, default=0)
    f.formula("fxCutoff30", "DateTime", "NOW() - 30")
    f.formula("fxCutoff3", "DateTime", "NOW() - 3")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.decision("Dec_Lead_Age", [
        ("Old_Lead", [("$Record.CreatedDate", "LessThan", R("fxCutoff30"))], "Dec_Has_Email"),
        ("Aging_Lead", [("$Record.CreatedDate", "LessThan", R("fxCutoff3"))], "Get_Open_Followups")],
        None, "Fresh")
    f.decision("Dec_Has_Email", [("Has_Email", [("$Record.Email", "IsNull", False)], "Get_Matching_Contact")], "Update_Lead_Cold", "No Email")
    f.get("Get_Matching_Contact", "Contact", [("Email", "EqualTo", R("$Record.Email"))], "Dec_Contact_Exists", "Log_Fault", first=True)
    f.decision("Dec_Contact_Exists", [("Contact_Exists", [("Get_Matching_Contact", "IsNull", False)], "Update_Lead_Closed")], "Update_Lead_Cold", "No Contact")
    f.update("Update_Lead_Closed", "Lead", [("Id", "EqualTo", R("$Record.Id"))], {"Status": "Closed - Not Converted"}, "Create_Duplicate_Note_Task", "Log_Fault")
    f.create("Create_Duplicate_Note_Task", "Task", {"Subject": PFX + "Lead closed: already a contact", "WhoId": R("Get_Matching_Contact.Id"),
                                                    "OwnerId": R("$Record.CreatedById"), "Priority": "Low", "Status": "Completed"}, None, "Log_Fault")
    f.update("Update_Lead_Cold", "Lead", [("Id", "EqualTo", R("$Record.Id"))], {"Rating": "Cold"}, None, "Log_Fault")
    f.get("Get_Open_Followups", "Task", [("WhoId", "EqualTo", R("$Record.Id")), ("IsClosed", "EqualTo", False), ("Subject", "StartsWith", PFX)],
          "Asg_Followup_Count", "Log_Fault")
    f.assign("Asg_Followup_Count", [("varOpenFollowups", "AssignCount", R("Get_Open_Followups"))], "Dec_Needs_Followup")
    f.decision("Dec_Needs_Followup", [("Needs_Followup", [("varOpenFollowups", "EqualTo", 0)], "Create_Followup_Task")], None, "Already Planned")
    f.create("Create_Followup_Task", "Task", {"Subject": PFX + "Daily lead follow-up", "WhoId": R("$Record.Id"), "OwnerId": R("$Record.CreatedById"),
                                              "ActivityDate": R("fxTomorrow"), "Priority": "Normal", "Status": "Not Started"}, None, "Log_Fault")
    log_fault(f, record=R("$Record.Id"))
    f.start("Dec_Lead_Age", obj="Lead", trigger="Scheduled",
            filters=[("IsConverted", "EqualTo", False), ("Status", "EqualTo", "Open - Not Contacted")],
            schedule=("Daily", START, "06:00:00.000Z"))
    return f


def task_cleanup():
    f = Flow("SCH_Weekly_Demo_Task_Cleanup", "SCH Weekly Demo Task Cleanup", "sch",
             "Weekly housekeeping limited to records created by these demo flows: deletes completed '[Flow Demo]' tasks and "
             "'[Flow Error]' logs older than 90 days, raises priority of overdue demo tasks, writes a summary Task and e-mail.")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varDeleted", "Number", scale=0, default=0)
    f.var("varRaised", "Number", scale=0, default=0)
    f.formula("fxCutoff90", "DateTime", "NOW() - 90")
    f.tt("ttSummary", "Weekly demo task cleanup ({!$Flow.CurrentDate})\nCompleted demo tasks deleted: {!varDeleted}\nOverdue demo tasks raised to High: {!varRaised}")
    f.get("Get_Completed_Demo_Tasks", "Task", [("Subject", "StartsWith", PFX), ("IsClosed", "EqualTo", True), ("CreatedDate", "LessThan", R("fxCutoff90"))],
          "Asg_Delete_Count", "Log_Fault")
    f.assign("Asg_Delete_Count", [("varDeleted", "AssignCount", R("Get_Completed_Demo_Tasks"))], "Dec_Anything_To_Delete")
    f.decision("Dec_Anything_To_Delete", [("Has_Old_Tasks", [("varDeleted", "GreaterThan", 0)], "Delete_Old_Demo_Tasks")], "Delete_Old_Error_Logs", "Nothing Old")
    f.delete("Delete_Old_Demo_Tasks", input_ref="Get_Completed_Demo_Tasks", nxt="Delete_Old_Error_Logs", fault="Log_Fault")
    f.delete("Delete_Old_Error_Logs", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("CreatedDate", "LessThan", R("fxCutoff90"))],
             "Get_Overdue_Demo_Tasks", "Log_Fault")
    f.get("Get_Overdue_Demo_Tasks", "Task", [("Subject", "StartsWith", PFX), ("IsClosed", "EqualTo", False), ("ActivityDate", "LessThan", R("$Flow.CurrentDate"))],
          "Filter_Not_High", "Log_Fault")
    f.filter_coll("Filter_Not_High", "Get_Overdue_Demo_Tasks", "Task", [("Priority", "NotEqualTo", "High")], "Loop_Overdue")
    f.loop("Loop_Overdue", "Filter_Not_High", "Asg_Raise_Priority", "Dec_Has_Changes", var="varTask")
    f.assign("Asg_Raise_Priority", [("varTask.Priority", "Assign", "High"), ("colTasksToUpdate", "Add", R("varTask")), ("varRaised", "Add", 1)], "Loop_Overdue")
    f.decision("Dec_Has_Changes", [("Has_Changes", [("varRaised", "GreaterThan", 0)], "Update_Overdue_Tasks")], "Create_Cleanup_Summary", "No Changes")
    f.update("Update_Overdue_Tasks", input_ref="colTasksToUpdate", nxt="Create_Cleanup_Summary", fault="Log_Fault")
    f.create("Create_Cleanup_Summary", "Task", {"Subject": PFX + "Weekly cleanup summary", "Description": R("ttSummary"), "Priority": "Low",
                                                "Status": "Completed", "ActivityDate": R("$Flow.CurrentDate")}, "Send_Cleanup_Email", "Log_Fault")
    f.email("Send_Cleanup_Email", R("$User.Email"), PFX + "Weekly cleanup summary", R("ttSummary"), None, "Log_Fault")
    log_fault(f)
    f.start("Get_Completed_Demo_Tasks", trigger="Scheduled", schedule=("Weekly", START, "02:00:00.000Z"))
    return f


ALL = [stale_opps, weekly_health, case_aging, lead_followup, task_cleanup]

from flowlib import Flow, R, D
from common import log_fault, admin_lookup, PFX


def batch_scope_router():
    f = Flow("PEF_Batch_Error_Scope_Router", "PEF Batch Error Scope Router", "pef",
             "Subscribes to BatchApexErrorEvent: takes the first record Id from JobScope, detects its object by key prefix "
             "(Account / Opportunity / Case), loads it and attaches a Task to that record and its owner; otherwise a general Task.")
    f.var("varFirstId", "String")
    f.var("varOwnerId", "String")
    f.formula("fxFirstId", "String", "LEFT(SUBSTITUTE(BLANKVALUE({!$Record.JobScope}, ''), ' ', ''), 18)")
    f.formula("fxPrefix", "String", "LEFT({!varFirstId}, 3)")
    f.tt("ttDetails", "Batch job {!$Record.AsyncApexJobId} failed on a scope that includes record {!varFirstId}.\n"
                      "{!$Record.ExceptionType}: {!$Record.Message}\nScope truncated: {!$Record.DoesExceedJobScopeMaxLength}")
    f.assign("Asg_First_Id", [("varFirstId", "Assign", R("fxFirstId"))], "Dec_Object_Type")
    f.decision("Dec_Object_Type", [
        ("Account_Scope", [("fxPrefix", "EqualTo", "001")], "Get_Account"),
        ("Opportunity_Scope", [("fxPrefix", "EqualTo", "006")], "Get_Opportunity"),
        ("Case_Scope", [("fxPrefix", "EqualTo", "500")], "Get_Case")], "Create_General_Task", "Other Object")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("varFirstId"))], "Asg_Account_Owner", "Log_Fault", first=True)
    f.assign("Asg_Account_Owner", [("varOwnerId", "Assign", R("Get_Account.OwnerId"))], "Dec_Owner_Found")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("varFirstId"))], "Asg_Opp_Owner", "Log_Fault", first=True)
    f.assign("Asg_Opp_Owner", [("varOwnerId", "Assign", R("Get_Opportunity.OwnerId"))], "Dec_Owner_Found")
    f.get("Get_Case", "Case", [("Id", "EqualTo", R("varFirstId"))], "Asg_Case_Owner", "Log_Fault", first=True)
    f.assign("Asg_Case_Owner", [("varOwnerId", "Assign", R("Get_Case.CreatedById"))], "Dec_Owner_Found")
    f.decision("Dec_Owner_Found", [("Owner_Found", [("varOwnerId", "IsNull", False)], "Create_Record_Task")], "Create_General_Task", "Record Missing")
    f.create("Create_Record_Task", "Task", {"Subject": PFX + "Batch job failed on this record", "WhatId": R("varFirstId"), "OwnerId": R("varOwnerId"),
                                            "Description": R("ttDetails"), "Priority": "High", "Status": "Not Started"}, "Sub_Log_Error", "Log_Fault")
    f.create("Create_General_Task", "Task", {"Subject": PFX + "Batch job failed (scope not routable)", "Description": R("ttDetails"),
                                             "Priority": "Normal", "Status": "Not Started"}, "Sub_Log_Error", "Log_Fault")
    f.subflow("Sub_Log_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexScope", "inErrorMessage": R("$Record.Message"),
                                                      "inRecordId": R("varFirstId"), "inSeverity": "Error"})
    log_fault(f, severity="Critical")
    f.start("Asg_First_Id", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def batch_daily_rollup():
    f = Flow("PEF_Batch_Error_Daily_Rollup", "PEF Batch Error Daily Rollup", "pef",
             "Subscribes to BatchApexErrorEvent: appends each error to one rollup Task per day (created on first error), counts the "
             "day's errors and e-mails an active admin once the count reaches 10.")
    f.var("varErrorCount", "Number", scale=0, default=0)
    f.var("varErr", "SObject", obj="Task")
    f.var("varRollupId", "String")
    f.formula("fxToday", "DateTime", "DATETIMEVALUE(TODAY())")
    f.formula("fxSubject", "String", f"'{PFX}Batch error rollup ' & TEXT(TODAY())")
    f.formula("fxLine", "String", "TEXT(NOW()) & ' | ' & BLANKVALUE({!$Record.Phase}, '?') & ' | ' & BLANKVALUE({!$Record.ExceptionType}, '') & ': ' & LEFT(BLANKVALUE({!$Record.Message}, ''), 300)")
    f.formula("fxAppended", "String", "LEFT(BLANKVALUE({!Get_Rollup_Task.Description}, '') & ' || ' & {!fxLine}, 31000)")
    f.tt("ttAlert", "{!varErrorCount} batch Apex errors were logged today. Latest: {!fxLine}")
    f.get("Get_Rollup_Task", "Task", [("Subject", "EqualTo", R("fxSubject")), ("CreatedDate", "GreaterThanOrEqualTo", R("fxToday"))],
          "Dec_Rollup_Exists", "Log_Fault", first=True)
    f.decision("Dec_Rollup_Exists", [("Exists", [("Get_Rollup_Task", "IsNull", False)], "Update_Rollup_Task")], "Create_Rollup_Task", "First Today")
    f.update("Update_Rollup_Task", "Task", [("Id", "EqualTo", R("Get_Rollup_Task.Id"))], {"Description": R("fxAppended")}, "Get_Todays_Errors", "Log_Fault")
    f.create("Create_Rollup_Task", "Task", {"Subject": R("fxSubject"), "Description": R("fxLine"), "Priority": "Normal", "Status": "Not Started",
                                            "ActivityDate": R("$Flow.CurrentDate")}, "Get_Todays_Errors", "Log_Fault", id_to="varRollupId")
    f.get("Get_Todays_Errors", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("CreatedDate", "GreaterThanOrEqualTo", R("fxToday"))],
          "Loop_Errors", "Log_Fault")
    f.loop("Loop_Errors", "Get_Todays_Errors", "Dec_Is_Batch_Error", "Dec_Threshold", var="varErr")
    f.decision("Dec_Is_Batch_Error", [("Batch_Error", [("varErr.Subject", "Contains", "Batch")], "Asg_Count")], "Loop_Errors", "Other Error")
    f.assign("Asg_Count", [("varErrorCount", "Add", 1)], "Loop_Errors")
    f.decision("Dec_Threshold", [("Threshold", [("varErrorCount", "EqualTo", 10)], "Get_Admin_Profile")], "Sub_Log_Error", "Below")
    admin_lookup(f, "Send_Threshold_Email", "Log_Fault")
    f.email("Send_Threshold_Email", R("Get_Admin_User.Email"), PFX + "10 batch errors today", R("ttAlert"), "Sub_Log_Error", "Log_Fault")
    f.subflow("Sub_Log_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexRollup", "inErrorMessage": R("fxLine"), "inSeverity": "Error"})
    log_fault(f, severity="Critical")
    f.start("Get_Rollup_Task", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_coaching():
    f = Flow("PEF_Flow_Error_User_Coaching", "PEF Flow Error User Coaching", "pef",
             "Subscribes to FlowExecutionErrorEvent: routes a coaching Task to the user's manager (or the user), counts the user's "
             "coaching tasks in the last 7 days and e-mails when the same user keeps hitting errors.")
    f.var("varAssigneeId", "String")
    f.var("varRecentCount", "Number", scale=0, default=0)
    f.formula("fxLast7Days", "DateTime", "NOW() - 7")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Flow error coaching: ' & {{!$Record.FlowApiName}}, 255)")
    f.tt("ttCoaching", "User {!Get_User.Username} hit an error in flow {!$Record.FlowApiName} at element {!$Record.ElementApiName}.\n"
                       "Error: {!$Record.ErrorMessage}\nCoaching tasks in the last 7 days: {!varRecentCount}")
    f.get("Get_User", "User", [("Id", "EqualTo", R("$Record.InterviewStartedById"))], "Dec_User_Active", "Log_Fault", first=True)
    f.decision("Dec_User_Active", [("Active", [("Get_User", "IsNull", False), ("Get_User.IsActive", "EqualTo", True)], "Dec_Has_Manager")], None, "Inactive")
    f.decision("Dec_Has_Manager", [("Has_Manager", [("Get_User.ManagerId", "IsNull", False)], "Get_Manager")], "Asg_Assign_User", "No Manager")
    f.get("Get_Manager", "User", [("Id", "EqualTo", R("Get_User.ManagerId")), ("IsActive", "EqualTo", True)], "Dec_Manager_Active", "Log_Fault", first=True)
    f.decision("Dec_Manager_Active", [("Manager_Active", [("Get_Manager", "IsNull", False)], "Asg_Assign_Manager")], "Asg_Assign_User", "Inactive Manager")
    f.assign("Asg_Assign_Manager", [("varAssigneeId", "Assign", R("Get_Manager.Id"))], "Get_Recent_Coaching")
    f.assign("Asg_Assign_User", [("varAssigneeId", "Assign", R("Get_User.Id"))], "Get_Recent_Coaching")
    f.get("Get_Recent_Coaching", "Task", [("Subject", "StartsWith", PFX + "Flow error coaching"), ("OwnerId", "EqualTo", R("varAssigneeId")),
                                          ("CreatedDate", "GreaterThan", R("fxLast7Days"))], "Asg_Recent_Count", "Log_Fault")
    f.assign("Asg_Recent_Count", [("varRecentCount", "AssignCount", R("Get_Recent_Coaching"))], "Create_Coaching_Task")
    f.create("Create_Coaching_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttCoaching"), "OwnerId": R("varAssigneeId"),
                                              "Priority": "Normal", "Status": "Not Started"}, "Dec_Repeated", "Log_Fault")
    f.decision("Dec_Repeated", [("Repeated", [("varRecentCount", "GreaterThanOrEqualTo", 3)], "Send_Repeat_Email")], None, "First Times")
    f.email("Send_Repeat_Email", R("Get_User.Email"), PFX + "Repeated flow errors", R("ttCoaching"), None, "Log_Fault")
    log_fault(f, severity="Error")
    f.start("Get_User", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_hotspot():
    f = Flow("PEF_Flow_Error_Hotspot_Detector", "PEF Flow Error Hotspot Detector", "pef",
             "Subscribes to FlowExecutionErrorEvent: looks at '[Flow Error]' logs of the same flow in the last 7 days, filters those for "
             "the same element, sorts newest first and opens one de-duplicated hotspot Task + e-mail when 3+ repeats are found.")
    f.var("varHits", "Number", scale=0, default=0)
    f.var("varDates", "String", default="")
    f.var("varHit", "SObject", obj="Task")
    f.formula("fxHitDate", "String", "TEXT({!varHit.CreatedDate})")
    f.formula("fxLast7Days", "DateTime", "NOW() - 7")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Error hotspot: ' & {{!$Record.FlowApiName}} & ' / ' & BLANKVALUE({{!$Record.ElementApiName}}, '?'), 255)")
    f.tt("ttHotspot", "Element {!$Record.ElementApiName} in flow {!$Record.FlowApiName} failed {!varHits} times in 7 days.\nRecent occurrences: {!varDates}\n"
                      "Latest error: {!$Record.ErrorMessage}")
    f.get("Get_Recent_Logs", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("Subject", "Contains", R("$Record.FlowApiName")),
                                      ("CreatedDate", "GreaterThan", R("fxLast7Days"))], "Sort_Newest", "Log_Fault")
    f.sort_coll("Sort_Newest", "Get_Recent_Logs", "CreatedDate", "Desc", "Filter_Same_Element")
    f.filter_coll("Filter_Same_Element", "Get_Recent_Logs", "Task", [("Description", "Contains", R("$Record.ElementApiName"))], "Asg_Hits")
    f.assign("Asg_Hits", [("varHits", "AssignCount", R("Filter_Same_Element"))], "Dec_Hotspot")
    f.decision("Dec_Hotspot", [("Hotspot", [("varHits", "GreaterThanOrEqualTo", 3)], "Loop_Hits")], "Sub_Log_Error", "Not Yet")
    f.loop("Loop_Hits", "Filter_Same_Element", "Asg_Append_Date", "Get_Existing_Hotspot", var="varHit")
    f.assign("Asg_Append_Date", [("varDates", "Add", R("fxHitDate")), ("varDates", "Add", "; ")], "Loop_Hits")
    f.get("Get_Existing_Hotspot", "Task", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Dec_Hotspot_Exists", "Log_Fault", first=True)
    f.decision("Dec_Hotspot_Exists", [("Exists", [("Get_Existing_Hotspot", "IsNull", False)], "Sub_Log_Error")], "Create_Hotspot_Task", "New Hotspot")
    f.create("Create_Hotspot_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttHotspot"), "Priority": "High", "Status": "Not Started"},
             "Send_Hotspot_Email", "Log_Fault")
    f.email("Send_Hotspot_Email", R("$User.Email"), R("fxSubject"), R("ttHotspot"), "Sub_Log_Error", "Log_Fault")
    f.subflow("Sub_Log_Error", "AUT_Log_Flow_Error", {"inFlowName": R("$Record.FlowApiName"), "inErrorMessage": R("$Record.ErrorMessage"),
                                                      "inRecordId": R("$Record.ElementApiName"), "inSeverity": "Error"})
    log_fault(f, severity="Critical")
    f.start("Get_Recent_Logs", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def status_alert_digest():
    f = Flow("PEF_Status_Alert_Service_Digest", "PEF Status Alert Service Digest", "pef",
             "Subscribes to PlatformStatusAlertEvent: maintains one daily digest Task per service (append or create), counts open "
             "digests for the day and escalates to an active admin when 3+ services report alerts.")
    f.var("varServiceKey", "String")
    f.var("varServicesToday", "Number", scale=0, default=0)
    f.formula("fxToday", "DateTime", "DATETIMEVALUE(TODAY())")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Service alerts ' & TEXT(TODAY()) & ': ' & {{!varServiceKey}}, 255)")
    f.formula("fxLine", "String", "TEXT({!$Record.EventDate}) & ' | ' & BLANKVALUE({!$Record.StatusType}, '?') & ' | ' & BLANKVALUE({!$Record.ComponentName}, '') & ' | ' & BLANKVALUE({!$Record.Subject}, '')")
    f.formula("fxAppended", "String", "LEFT(BLANKVALUE({!Get_Digest_Task.Description}, '') & ' || ' & {!fxLine}, 31000)")
    f.tt("ttEscalation", "{!varServicesToday} services reported platform status alerts today. Latest: {!fxLine}")
    f.decision("Dec_Service_Known", [("Known", [("$Record.ServiceName", "IsNull", False)], "Asg_Service_Name")], "Asg_Service_Unknown", "Unknown")
    f.assign("Asg_Service_Name", [("varServiceKey", "Assign", R("$Record.ServiceName"))], "Get_Digest_Task")
    f.assign("Asg_Service_Unknown", [("varServiceKey", "Assign", "Unknown service")], "Get_Digest_Task")
    f.get("Get_Digest_Task", "Task", [("Subject", "EqualTo", R("fxSubject")), ("CreatedDate", "GreaterThanOrEqualTo", R("fxToday"))],
          "Dec_Digest_Exists", "Log_Fault", first=True)
    f.decision("Dec_Digest_Exists", [("Exists", [("Get_Digest_Task", "IsNull", False)], "Update_Digest_Task")], "Create_Digest_Task", "First Alert")
    f.update("Update_Digest_Task", "Task", [("Id", "EqualTo", R("Get_Digest_Task.Id"))], {"Description": R("fxAppended")}, "Sub_Log_Alert", "Log_Fault")
    f.create("Create_Digest_Task", "Task", {"Subject": R("fxSubject"), "Description": R("fxLine"), "Priority": "Normal", "Status": "Not Started",
                                            "ActivityDate": R("$Flow.CurrentDate")}, "Get_Todays_Digests", "Log_Fault")
    f.get("Get_Todays_Digests", "Task", [("Subject", "StartsWith", PFX + "Service alerts"), ("CreatedDate", "GreaterThanOrEqualTo", R("fxToday"))],
          "Asg_Service_Count", "Log_Fault")
    f.assign("Asg_Service_Count", [("varServicesToday", "AssignCount", R("Get_Todays_Digests"))], "Dec_Many_Services")
    f.decision("Dec_Many_Services", [("Many", [("varServicesToday", "EqualTo", 3)], "Get_Admin_Profile")], "Sub_Log_Alert", "Few")
    admin_lookup(f, "Send_Escalation_Email", "Log_Fault")
    f.email("Send_Escalation_Email", R("Get_Admin_User.Email"), PFX + "Multiple services alerting", R("ttEscalation"), "Sub_Log_Alert", "Log_Fault")
    f.subflow("Sub_Log_Alert", "AUT_Log_Flow_Error", {"inFlowName": "PlatformStatusAlert", "inErrorMessage": R("fxLine"), "inSeverity": "Warning"})
    log_fault(f, severity="Critical")
    f.start("Dec_Service_Known", obj="PlatformStatusAlertEvent", trigger="PlatformEvent")
    return f


ALL = [batch_scope_router, batch_daily_rollup, flow_error_coaching, flow_error_hotspot, status_alert_digest]

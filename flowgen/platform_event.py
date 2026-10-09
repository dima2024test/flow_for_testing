from flowlib import Flow, R, D
from common import log_fault, admin_lookup, PFX


def batch_logger():
    f = Flow("PEF_Batch_Apex_Error_Logger", "PEF Batch Apex Error Logger", "pef",
             "Subscribes to BatchApexErrorEvent: classifies severity by phase, finds an active System Administrator, creates a Task "
             "with full exception details, e-mails on critical phases and records the error via the shared logger subflow.")
    f.var("varSeverity", "String", default="Error")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Batch Apex error: ' & BLANKVALUE({{!$Record.ExceptionType}}, 'Unknown') & ' [' & BLANKVALUE({{!$Record.Phase}}, '?') & ']', 255)")
    f.tt("ttDetails", "Async job: {!$Record.AsyncApexJobId}\nPhase: {!$Record.Phase}\nException: {!$Record.ExceptionType}\n"
                      "Message: {!$Record.Message}\nRequest Id: {!$Record.RequestId}\n\nStack trace:\n{!$Record.StackTrace}\n\nJob scope:\n{!$Record.JobScope}")
    f.decision("Dec_Phase", [("Start_Or_Finish", [("$Record.Phase", "EqualTo", "START"), ("$Record.Phase", "EqualTo", "FINISH")], "Asg_Severity_Critical", "or")],
               "Asg_Severity_Error", "Execute Phase")
    f.assign("Asg_Severity_Critical", [("varSeverity", "Assign", "Critical")], "Get_Admin_Profile")
    f.assign("Asg_Severity_Error", [("varSeverity", "Assign", "Error")], "Get_Admin_Profile")
    admin_lookup(f, "Dec_Admin_Found", "Log_Fault")
    f.decision("Dec_Admin_Found", [("Admin_Found", [("Get_Admin_User", "IsNull", False)], "Create_Task_For_Admin")], "Create_Task_Default_Owner", "No Admin")
    f.create("Create_Task_For_Admin", "Task", {"Subject": R("fxSubject"), "Description": R("ttDetails"), "OwnerId": R("Get_Admin_User.Id"),
                                               "Priority": "High", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Dec_Is_Critical", "Log_Fault")
    f.create("Create_Task_Default_Owner", "Task", {"Subject": R("fxSubject"), "Description": R("ttDetails"),
                                                   "Priority": "High", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Sub_Log_Batch_Error", "Log_Fault")
    f.decision("Dec_Is_Critical", [("Critical", [("varSeverity", "EqualTo", "Critical")], "Send_Critical_Email")], "Sub_Log_Batch_Error", "Not Critical")
    f.email("Send_Critical_Email", R("Get_Admin_User.Email"), R("fxSubject"), R("ttDetails"), "Sub_Log_Batch_Error", "Sub_Log_Batch_Error")
    f.subflow("Sub_Log_Batch_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexJob", "inErrorMessage": R("$Record.Message"),
                                                            "inRecordId": R("$Record.AsyncApexJobId"), "inSeverity": R("varSeverity"),
                                                            "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Dec_Phase", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def batch_case():
    f = Flow("PEF_Batch_Apex_Error_Case_Creator", "PEF Batch Apex Error Case Creator", "pef",
             "Subscribes to BatchApexErrorEvent: de-duplicates by exception type, appends to the newest open Case if one exists, "
             "otherwise creates a new Case (owner = active admin) with phase-based priority and notifies by e-mail.")
    f.var("varSubject", "String")
    f.var("varPriority", "String", default="Medium")
    f.var("varExistingCount", "Number", scale=0, default=0)
    f.var("varCase", "SObject", obj="Case")
    f.var("colCasesToUpdate", "SObject", coll=True, obj="Case")
    f.var("varNewCaseId", "String")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Batch failure: ' & BLANKVALUE({{!$Record.ExceptionType}}, 'Unknown exception'), 255)")
    f.formula("fxAppendedDescription", "String",
              "LEFT(BLANKVALUE({!varCase.Description}, '') & BR() & '--- Repeat at ' & TEXT(NOW()) & ': ' & BLANKVALUE({!$Record.Message}, ''), 31000)")
    f.tt("ttDescription", "Batch Apex job {!$Record.AsyncApexJobId} failed in phase {!$Record.Phase}.\n{!$Record.ExceptionType}: {!$Record.Message}\n\n{!$Record.StackTrace}")
    f.assign("Asg_Build_Subject", [("varSubject", "Assign", R("fxSubject"))], "Get_Existing_Cases")
    f.get("Get_Existing_Cases", "Case", [("Subject", "EqualTo", R("varSubject")), ("IsClosed", "EqualTo", False)], "Asg_Existing_Count", "Log_Fault")
    f.assign("Asg_Existing_Count", [("varExistingCount", "AssignCount", R("Get_Existing_Cases"))], "Dec_Case_Exists")
    f.decision("Dec_Case_Exists", [("Case_Exists", [("varExistingCount", "GreaterThan", 0)], "Sort_Newest_First")], "Dec_Case_Priority", "New Problem")
    f.sort_coll("Sort_Newest_First", "Get_Existing_Cases", "CreatedDate", "Desc", "Loop_Existing_Cases", limit=1)
    f.loop("Loop_Existing_Cases", "Get_Existing_Cases", "Asg_Append_Occurrence", "Update_Existing_Cases", var="varCase")
    f.assign("Asg_Append_Occurrence", [("varCase.Description", "Assign", R("fxAppendedDescription")), ("varCase.Priority", "Assign", "High"),
                                       ("colCasesToUpdate", "Add", R("varCase"))], "Loop_Existing_Cases")
    f.update("Update_Existing_Cases", input_ref="colCasesToUpdate", fault="Log_Fault")
    f.decision("Dec_Case_Priority", [("Execute_Phase", [("$Record.Phase", "EqualTo", "EXECUTE")], "Asg_Priority_Medium")], "Asg_Priority_High", "Start or Finish")
    f.assign("Asg_Priority_Medium", [("varPriority", "Assign", "Medium")], "Get_Admin_Profile")
    f.assign("Asg_Priority_High", [("varPriority", "Assign", "High")], "Get_Admin_Profile")
    admin_lookup(f, "Dec_Admin_Found", "Log_Fault")
    f.decision("Dec_Admin_Found", [("Admin_Found", [("Get_Admin_User", "IsNull", False)], "Create_Case")], "Log_Fault", "No Admin")
    f.create("Create_Case", "Case", {"Subject": R("varSubject"), "Description": R("ttDescription"), "Priority": R("varPriority"), "Origin": "Web",
                                     "Status": "New", "OwnerId": R("Get_Admin_User.Id")},
             "Send_Case_Email", "Log_Fault", id_to="varNewCaseId")
    f.email("Send_Case_Email", R("Get_Admin_User.Email"), R("varSubject"), R("ttDescription"), None, "Log_Fault")
    log_fault(f, severity="Critical")
    f.start("Asg_Build_Subject", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_monitor():
    f = Flow("PEF_Flow_Error_Monitor", "PEF Flow Error Monitor", "pef",
             "Subscribes to FlowExecutionErrorEvent (screen flow errors): categorises the failing element, resolves the user, counts "
             "similar errors in the last 24h and alerts when the threshold is reached; always logs via the shared logger.")
    f.var("varCategory", "String")
    f.var("varUserLabel", "String")
    f.var("varOwnerId", "String")
    f.var("varSeverity", "String", default="Error")
    f.var("varRecentCount", "Number", scale=0, default=0)
    f.formula("fxLast24h", "DateTime", "NOW() - 1")
    f.formula("fxMessage", "String", "LEFT('[' & {!varCategory} & '] ' & {!$Record.ElementApiName} & ': ' & BLANKVALUE({!$Record.ErrorMessage}, 'n/a'), 3000)")
    f.tt("ttAlert", "Flow {!$Record.FlowApiName} failed {!varRecentCount} times in the last 24h.\nLast element: {!$Record.ElementApiName} ({!$Record.ElementType})\n"
                    "User: {!varUserLabel}\nError: {!$Record.ErrorMessage}")
    f.get("Get_Interview_User", "User", [("Id", "EqualTo", R("$Record.InterviewStartedById"))], "Dec_User_Found", "Log_Fault", first=True)
    f.decision("Dec_User_Found", [("User_Found", [("Get_Interview_User", "IsNull", False), ("Get_Interview_User.IsActive", "EqualTo", True)], "Asg_User_Context")],
               "Asg_Unknown_User", "Unknown")
    f.assign("Asg_User_Context", [("varUserLabel", "Assign", R("Get_Interview_User.Username")), ("varOwnerId", "Assign", R("Get_Interview_User.Id"))], "Dec_Error_Type")
    f.assign("Asg_Unknown_User", [("varUserLabel", "Assign", "unknown or inactive user")], "Dec_Error_Type")
    f.decision("Dec_Error_Type", [
        ("Data_Operation", [("$Record.ElementType", "Contains", "Record")], "Asg_Category_Data"),
        ("Action_Call", [("$Record.ElementType", "Contains", "Action")], "Asg_Category_Action")],
        "Asg_Category_Other", "Other")
    f.assign("Asg_Category_Data", [("varCategory", "Assign", "DATA"), ("varSeverity", "Assign", "Critical")], "Get_Recent_Error_Logs")
    f.assign("Asg_Category_Action", [("varCategory", "Assign", "ACTION")], "Get_Recent_Error_Logs")
    f.assign("Asg_Category_Other", [("varCategory", "Assign", "OTHER")], "Get_Recent_Error_Logs")
    f.get("Get_Recent_Error_Logs", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("Subject", "Contains", R("$Record.FlowApiName")),
                                            ("CreatedDate", "GreaterThan", R("fxLast24h"))], "Asg_Recent_Count", "Log_Fault")
    f.assign("Asg_Recent_Count", [("varRecentCount", "AssignCount", R("Get_Recent_Error_Logs"))], "Dec_Threshold")
    f.decision("Dec_Threshold", [("Threshold_Reached", [("varRecentCount", "GreaterThanOrEqualTo", 5)], "Send_Threshold_Email")], "Sub_Log_Flow_Error", "Below Threshold")
    f.email("Send_Threshold_Email", R("$User.Email"), PFX + "Repeated screen flow failures", R("ttAlert"), "Sub_Log_Flow_Error", "Sub_Log_Flow_Error")
    f.subflow("Sub_Log_Flow_Error", "AUT_Log_Flow_Error", {"inFlowName": R("$Record.FlowApiName"), "inErrorMessage": R("fxMessage"),
                                                           "inRecordId": R("$Record.InterviewGuid"), "inSeverity": R("varSeverity"),
                                                           "inOwnerId": R("varOwnerId")})
    log_fault(f, severity="Critical")
    f.start("Get_Interview_User", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_case():
    f = Flow("PEF_Flow_Error_Case_Escalation", "PEF Flow Error Case Escalation", "pef",
             "Subscribes to FlowExecutionErrorEvent: one open Case per failing flow (existing case gets the occurrence appended), "
             "owned by an active admin, plus a follow-up Task for the user who hit the error.")
    f.var("varPriority", "String")
    f.var("varCaseId", "String")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Flow failure: ' & {{!$Record.FlowApiName}}, 255)")
    f.formula("fxAppended", "String",
              "LEFT(BLANKVALUE({!Get_Open_Error_Case.Description}, '') & BR() & TEXT({!$Record.EventDate}) & ' - ' & {!$Record.ElementApiName} & ': ' & BLANKVALUE({!$Record.ErrorMessage}, ''), 31000)")
    f.tt("ttDescription", "Flow: {!$Record.FlowApiName} (version {!$Record.FlowVersionId})\nInterview: {!$Record.InterviewGuid}\n"
                          "Element: {!$Record.ElementApiName} ({!$Record.ElementType})\nError: {!$Record.ErrorMessage}")
    f.decision("Dec_Flow_Category", [("Demo_Screen_Flow", [("$Record.FlowApiName", "StartsWith", "SCR_")], "Asg_Priority_Medium")], "Asg_Priority_High", "Other Flow")
    f.assign("Asg_Priority_Medium", [("varPriority", "Assign", "Medium")], "Get_Open_Error_Case")
    f.assign("Asg_Priority_High", [("varPriority", "Assign", "High")], "Get_Open_Error_Case")
    f.get("Get_Open_Error_Case", "Case", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Dec_Case_Exists", "Log_Fault",
          first=True, sort="CreatedDate", order="Desc")
    f.decision("Dec_Case_Exists", [("Case_Exists", [("Get_Open_Error_Case", "IsNull", False)], "Update_Existing_Case")], "Get_Admin_Profile", "New Failure")
    f.update("Update_Existing_Case", "Case", [("Id", "EqualTo", R("Get_Open_Error_Case.Id"))], {"Description": R("fxAppended"), "Priority": R("varPriority")},
             None, "Log_Fault")
    admin_lookup(f, "Dec_Admin_Found", "Log_Fault")
    f.decision("Dec_Admin_Found", [("Admin_Found", [("Get_Admin_User", "IsNull", False)], "Create_Case_For_Admin")], "Create_Case_Default_Owner", "No Admin")
    f.create("Create_Case_For_Admin", "Case", {"Subject": R("fxSubject"), "Description": R("ttDescription"), "Priority": R("varPriority"),
                                               "Origin": "Web", "Status": "New", "OwnerId": R("Get_Admin_User.Id")},
             "Create_Followup_Task", "Log_Fault", id_to="varCaseId")
    f.create("Create_Case_Default_Owner", "Case", {"Subject": R("fxSubject"), "Description": R("ttDescription"), "Priority": R("varPriority"),
                                                   "Origin": "Web", "Status": "New"},
             "Create_Followup_Task", "Log_Fault", id_to="varCaseId")
    f.create("Create_Followup_Task", "Task", {"Subject": PFX + "A flow you ran failed - support case opened", "WhatId": R("varCaseId"),
                                              "OwnerId": R("$Record.InterviewStartedById"), "Priority": "Normal", "Status": "Not Started"},
             "Send_Notification_Email", "Log_Fault")
    f.email("Send_Notification_Email", R("Get_Admin_User.Email"), R("fxSubject"), R("ttDescription"), None, "Log_Fault")
    log_fault(f, severity="Critical")
    f.start("Dec_Flow_Category", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def status_alert():
    f = Flow("PEF_Platform_Status_Alert_Handler", "PEF Platform Status Alert Handler", "pef",
             "Subscribes to PlatformStatusAlertEvent: classifies severity, routes a Task to the affected user (or an active admin), "
             "e-mails on failures and logs via the shared logger.")
    f.var("varSeverity", "String", default="Info")
    f.var("varOwnerId", "String")
    f.var("varNotifyEmail", "String")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Platform alert: ' & BLANKVALUE({{!$Record.Subject}}, BLANKVALUE({{!$Record.ComponentName}}, 'unknown')), 255)")
    f.tt("ttDetails", "Status: {!$Record.StatusType}\nService: {!$Record.ServiceName}\nComponent: {!$Record.ComponentName} / {!$Record.SubComponentName}\n"
                      "API error code: {!$Record.ApiErrorCode}\nUser: {!$Record.Username}\nRequest: {!$Record.RequestId}\nEvent date: {!$Record.EventDate}")
    f.decision("Dec_Status_Type", [
        ("Failure", [("$Record.StatusType", "Contains", "Fail")], "Asg_Critical"),
        ("Warning", [("$Record.StatusType", "Contains", "Warn")], "Asg_Warning")],
        "Asg_Info", "Informational")
    f.assign("Asg_Critical", [("varSeverity", "Assign", "Critical")], "Get_Affected_User")
    f.assign("Asg_Warning", [("varSeverity", "Assign", "Warning")], "Get_Affected_User")
    f.assign("Asg_Info", [("varSeverity", "Assign", "Info")], "Get_Affected_User")
    f.get("Get_Affected_User", "User", [("Id", "EqualTo", R("$Record.UserId")), ("IsActive", "EqualTo", True)], "Dec_User_Found", "Log_Fault", first=True)
    f.decision("Dec_User_Found", [("User_Found", [("Get_Affected_User", "IsNull", False)], "Asg_User_Owner")], "Get_Admin_Profile", "Use Admin")
    f.assign("Asg_User_Owner", [("varOwnerId", "Assign", R("Get_Affected_User.Id")), ("varNotifyEmail", "Assign", R("Get_Affected_User.Email"))], "Create_Alert_Task")
    admin_lookup(f, "Dec_Admin_Found", "Log_Fault")
    f.decision("Dec_Admin_Found", [("Admin_Found", [("Get_Admin_User", "IsNull", False)], "Asg_Admin_Owner")], "Log_Fault", "No Admin")
    f.assign("Asg_Admin_Owner", [("varOwnerId", "Assign", R("Get_Admin_User.Id")), ("varNotifyEmail", "Assign", R("Get_Admin_User.Email"))], "Create_Alert_Task")
    f.create("Create_Alert_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttDetails"), "OwnerId": R("varOwnerId"),
                                           "Priority": "High", "Status": "Not Started"}, "Dec_Is_Critical", "Log_Fault")
    f.decision("Dec_Is_Critical", [("Critical", [("varSeverity", "EqualTo", "Critical")], "Send_Alert_Email")], "Sub_Log_Alert", "Not Critical")
    f.email("Send_Alert_Email", R("varNotifyEmail"), R("fxSubject"), R("ttDetails"), "Sub_Log_Alert", "Sub_Log_Alert")
    f.subflow("Sub_Log_Alert", "AUT_Log_Flow_Error", {"inFlowName": f.api, "inErrorMessage": R("ttDetails"), "inSeverity": R("varSeverity"),
                                                      "inOwnerId": R("varOwnerId")})
    log_fault(f, severity="Critical")
    f.start("Dec_Status_Type", obj="PlatformStatusAlertEvent", trigger="PlatformEvent")
    return f


ALL = [batch_logger, batch_case, flow_error_monitor, flow_error_case, status_alert]

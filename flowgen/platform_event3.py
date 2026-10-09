from flowlib import Flow, R, D
from common import log_fault, admin_lookup, PFX


def batch_phase_retry():
    f = Flow("PEF_Batch_Phase_Retry_Planner", "PEF Batch Phase Retry Planner", "pef",
             "Subscribes to BatchApexErrorEvent: picks a phase-specific retry strategy (START / EXECUTE / FINISH), counts earlier retry "
             "attempts for the same async job and creates a dated retry Task for an active admin, or an escalated Case once 3 attempts failed.")
    f.var("varRetryHint", "String")
    f.var("varDueOffset", "Number", scale=0, default=0)
    f.var("varAttempts", "Number", scale=0, default=0)
    f.var("varAttemptDates", "String", default="")
    f.var("varPrior", "SObject", obj="Task")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Batch retry: job ' & BLANKVALUE({{!$Record.AsyncApexJobId}}, 'unknown'), 255)")
    f.formula("fxDueDate", "Date", "TODAY() + {!varDueOffset}")
    f.formula("fxPriorLine", "String", "TEXT({!varPrior.CreatedDate}) & ' (' & TEXT({!varPrior.Status}) & ')'")
    f.tt("ttRetry", "Batch job {!$Record.AsyncApexJobId} failed in phase {!$Record.Phase}.\nRetry strategy: {!varRetryHint}\n"
                    "{!$Record.ExceptionType}: {!$Record.Message}\nScope truncated: {!$Record.DoesExceedJobScopeMaxLength}\n"
                    "Previous attempts ({!varAttempts}): {!varAttemptDates}\n\nJob scope:\n{!$Record.JobScope}")
    f.decision("Dec_Phase", [
        ("Start_Phase", [("$Record.Phase", "EqualTo", "START")], "Asg_Start_Hint"),
        ("Finish_Phase", [("$Record.Phase", "EqualTo", "FINISH")], "Asg_Finish_Hint")],
        "Asg_Execute_Hint", "Execute Phase")
    f.assign("Asg_Start_Hint", [("varRetryHint", "Assign", "Fix the start() query / locator, then re-run the whole job today."),
                                ("varDueOffset", "Assign", 0)], "Get_Admin_Profile")
    f.assign("Asg_Finish_Hint", [("varRetryHint", "Assign", "Records were processed - re-run only the finish() logic / chained job."),
                                 ("varDueOffset", "Assign", 2)], "Get_Admin_Profile")
    f.assign("Asg_Execute_Hint", [("varRetryHint", "Assign", "Re-run only the failed scope records with a smaller batch size."),
                                  ("varDueOffset", "Assign", 1)], "Get_Admin_Profile")
    admin_lookup(f, "Get_Prior_Attempts", "Log_Fault")
    f.get("Get_Prior_Attempts", "Task", [("Subject", "EqualTo", R("fxSubject"))], "Loop_Prior_Attempts", "Log_Fault", sort="CreatedDate", order="Asc")
    f.loop("Loop_Prior_Attempts", "Get_Prior_Attempts", "Asg_Collect_Attempt", "Dec_Retry_Budget", var="varPrior")
    f.assign("Asg_Collect_Attempt", [("varAttempts", "Add", 1), ("varAttemptDates", "Add", R("fxPriorLine")), ("varAttemptDates", "Add", "; ")],
             "Loop_Prior_Attempts")
    f.decision("Dec_Retry_Budget", [("Budget_Exhausted", [("varAttempts", "GreaterThanOrEqualTo", 3)], "Create_Escalation_Case")],
               "Create_Retry_Task", "Retry Allowed")
    f.create("Create_Escalation_Case", "Case", {"Subject": R("fxSubject"), "Description": R("ttRetry"), "Priority": "High", "Status": "Escalated",
                                                "Origin": "Web", "OwnerId": R("Get_Admin_User.Id")}, "Sub_Log_Retry", "Log_Fault")
    f.create("Create_Retry_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttRetry"), "OwnerId": R("Get_Admin_User.Id"),
                                           "Priority": "High", "Status": "Not Started", "ActivityDate": R("fxDueDate")}, "Sub_Log_Retry", "Log_Fault")
    f.subflow("Sub_Log_Retry", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexRetry", "inErrorMessage": R("$Record.Message"),
                                                      "inRecordId": R("$Record.AsyncApexJobId"), "inSeverity": "Warning",
                                                      "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Dec_Phase", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def batch_request_correlator():
    f = Flow("PEF_Batch_Error_Request_Correlator", "PEF Batch Error Request Correlator", "pef",
             "Subscribes to BatchApexErrorEvent: correlates the event's RequestId / AsyncApexJobId with '[Flow Error]' log Tasks of the "
             "last hour (collection filter on Description) and, when related logs exist, creates one correlation Task for an admin and e-mails it.")
    f.var("varMatchCount", "Number", scale=0, default=0)
    f.var("varMatchedLogs", "String", default="")
    f.var("varLog", "SObject", obj="Task")
    f.formula("fxLastHour", "DateTime", "NOW() - (1/24)")
    f.formula("fxLogLine", "String", "LEFT(TEXT({!varLog.CreatedDate}) & ' ' & {!varLog.Subject}, 300)")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Correlated batch failure, request ' & {{!$Record.RequestId}}, 255)")
    f.tt("ttCorrelation", "Batch job {!$Record.AsyncApexJobId} (request {!$Record.RequestId}) failed in phase {!$Record.Phase}: "
                          "{!$Record.ExceptionType} - {!$Record.Message}\n\n{!varMatchCount} related error logs in the last hour:\n{!varMatchedLogs}")
    f.decision("Dec_Has_Request_Id", [("Has_Request", [("$Record.RequestId", "IsNull", False)], "Get_Recent_Error_Logs")], "Sub_Log_Batch_Error", "No Request Id")
    f.get("Get_Recent_Error_Logs", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("CreatedDate", "GreaterThan", R("fxLastHour"))],
          "Filter_Same_Request", "Log_Fault")
    f.filter_coll("Filter_Same_Request", "Get_Recent_Error_Logs", "Task",
                  [("Description", "Contains", R("$Record.RequestId")), ("Description", "Contains", R("$Record.AsyncApexJobId"))], "Asg_Match_Count", logic="or")
    f.assign("Asg_Match_Count", [("varMatchCount", "AssignCount", R("Filter_Same_Request"))], "Dec_Has_Matches")
    f.decision("Dec_Has_Matches", [("Has_Matches", [("varMatchCount", "GreaterThan", 0)], "Loop_Matches")], "Sub_Log_Batch_Error", "Isolated Error")
    f.loop("Loop_Matches", "Filter_Same_Request", "Asg_Append_Match", "Get_Admin_Profile", var="varLog")
    f.assign("Asg_Append_Match", [("varMatchedLogs", "Add", R("fxLogLine")), ("varMatchedLogs", "Add", " || ")], "Loop_Matches")
    admin_lookup(f, "Create_Correlation_Task", "Log_Fault")
    f.create("Create_Correlation_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttCorrelation"), "OwnerId": R("Get_Admin_User.Id"),
                                                 "Priority": "High", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Send_Correlation_Email", "Log_Fault")
    f.email("Send_Correlation_Email", R("Get_Admin_User.Email"), R("fxSubject"), R("ttCorrelation"), "Sub_Log_Batch_Error", "Log_Fault")
    f.subflow("Sub_Log_Batch_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexCorrelation", "inErrorMessage": R("$Record.Message"),
                                                            "inRecordId": R("$Record.AsyncApexJobId"), "inSeverity": "Error"})
    log_fault(f, severity="Critical")
    f.start("Dec_Has_Request_Id", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def batch_weekly_counter():
    f = Flow("PEF_Batch_Error_Weekly_Counter", "PEF Batch Error Weekly Counter", "pef",
             "Subscribes to BatchApexErrorEvent: keeps one counter Task per week and exception type (count in CallDurationInSeconds), "
             "deletes counter Tasks older than 8 weeks when a new week starts and e-mails an admin when a type reaches 25 errors in a week.")
    f.var("varCount", "Number", scale=0, default=1)
    f.var("varStale", "SObject", obj="Task")
    f.var("colStale", "SObject", coll=True, obj="Task")
    f.formula("fxWeekStart", "Date", "TODAY() - MOD(WEEKDAY(TODAY()) + 5, 7)")
    f.formula("fxWeekEnd", "Date", "{!fxWeekStart} + 6")
    f.formula("fxCutoff", "DateTime", "NOW() - 56")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Batch errors week of ' & TEXT({{!fxWeekStart}}) & ': ' & BLANKVALUE({{!$Record.ExceptionType}}, 'Unknown'), 255)")
    f.formula("fxNextCount", "Number", "BLANKVALUE({!Get_Week_Counter.CallDurationInSeconds}, 0) + 1", scale=0)
    f.formula("fxLine", "String", "TEXT(NOW()) & ' [' & BLANKVALUE({!$Record.Phase}, '?') & '] ' & LEFT(BLANKVALUE({!$Record.Message}, ''), 200)")
    f.formula("fxAppended", "String", "LEFT(BLANKVALUE({!Get_Week_Counter.Description}, '') & ' || ' & {!fxLine}, 31000)")
    f.tt("ttThreshold", "Exception type {!$Record.ExceptionType} reached {!varCount} batch Apex errors in the week starting {!fxWeekStart}.\nLatest: {!fxLine}")
    admin_lookup(f, "Get_Week_Counter", "Log_Fault")
    f.get("Get_Week_Counter", "Task", [("Subject", "EqualTo", R("fxSubject"))], "Dec_Counter_Exists", "Log_Fault", first=True)
    f.decision("Dec_Counter_Exists", [("Counter_Exists", [("Get_Week_Counter", "IsNull", False)], "Asg_Next_Count")], "Create_Week_Counter", "First This Week")
    f.assign("Asg_Next_Count", [("varCount", "Assign", R("fxNextCount"))], "Update_Week_Counter")
    f.update("Update_Week_Counter", "Task", [("Id", "EqualTo", R("Get_Week_Counter.Id"))],
             {"CallDurationInSeconds": R("varCount"), "Description": R("fxAppended")}, "Dec_Threshold", "Log_Fault")
    f.create("Create_Week_Counter", "Task", {"Subject": R("fxSubject"), "Description": R("fxLine"), "CallDurationInSeconds": 1,
                                             "OwnerId": R("Get_Admin_User.Id"), "Priority": "Low", "Status": "In Progress",
                                             "ActivityDate": R("fxWeekEnd")}, "Get_Stale_Counters", "Log_Fault")
    f.get("Get_Stale_Counters", "Task", [("Subject", "StartsWith", PFX + "Batch errors week of"), ("CreatedDate", "LessThan", R("fxCutoff"))],
          "Loop_Stale_Counters", "Log_Fault")
    f.loop("Loop_Stale_Counters", "Get_Stale_Counters", "Asg_Collect_Stale", "Delete_Stale_Counters", var="varStale")
    f.assign("Asg_Collect_Stale", [("colStale", "Add", R("varStale"))], "Loop_Stale_Counters")
    f.delete("Delete_Stale_Counters", input_ref="colStale", nxt="Sub_Log_Batch_Error", fault="Log_Fault")
    f.decision("Dec_Threshold", [("Threshold_Reached", [("varCount", "EqualTo", 25)], "Send_Threshold_Email")], "Sub_Log_Batch_Error", "Below Threshold")
    f.email("Send_Threshold_Email", R("Get_Admin_User.Email"), PFX + "Weekly batch error threshold reached", R("ttThreshold"), "Sub_Log_Batch_Error", "Log_Fault")
    f.subflow("Sub_Log_Batch_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexWeekly", "inErrorMessage": R("fxLine"),
                                                            "inRecordId": R("$Record.AsyncApexJobId"), "inSeverity": "Error",
                                                            "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Get_Admin_Profile", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def batch_keyword_classifier():
    f = Flow("PEF_Batch_Error_Keyword_Classifier", "PEF Batch Error Keyword Classifier", "pef",
             "Subscribes to BatchApexErrorEvent: classifies the error message by keyword (row lock, governor limits, CPU/heap, data "
             "validation), closes category Tasks older than 7 days and opens a fresh category Task with remediation advice when none is current.")
    f.var("varCategory", "String")
    f.var("varAdvice", "String")
    f.var("varPriority", "String", default="Normal")
    f.var("varFreshCount", "Number", scale=0, default=0)
    f.var("varCat", "SObject", obj="Task")
    f.var("colToClose", "SObject", coll=True, obj="Task")
    f.formula("fxWeekAgo", "DateTime", "NOW() - 7")
    f.formula("fxSubject", "String", f"'{PFX}Batch error category: ' & {{!varCategory}}")
    f.tt("ttCategory", "Category: {!varCategory}\nAdvice: {!varAdvice}\n\nFirst seen in job {!$Record.AsyncApexJobId} (phase {!$Record.Phase}):\n"
                       "{!$Record.ExceptionType}: {!$Record.Message}\n\n{!$Record.StackTrace}")
    f.decision("Dec_Keyword", [
        ("Row_Lock", [("$Record.Message", "Contains", "UNABLE_TO_LOCK_ROW")], "Asg_Locking"),
        ("Governor_Limit", [("$Record.Message", "Contains", "Too many SOQL"), ("$Record.Message", "Contains", "Too many DML")], "Asg_Limits", "or"),
        ("Resources", [("$Record.Message", "Contains", "CPU time"), ("$Record.Message", "Contains", "heap size")], "Asg_Resources", "or"),
        ("Data_Quality", [("$Record.Message", "Contains", "FIELD_CUSTOM_VALIDATION_EXCEPTION"),
                          ("$Record.Message", "Contains", "REQUIRED_FIELD_MISSING")], "Asg_Data", "or")],
        "Asg_Unclassified", "Unclassified")
    f.assign("Asg_Locking", [("varCategory", "Assign", "Record locking"), ("varPriority", "Assign", "Normal"),
                             ("varAdvice", "Assign", "Reduce batch size and order scope by parent Id to avoid lock contention.")], "Get_Admin_Profile")
    f.assign("Asg_Limits", [("varCategory", "Assign", "Governor limits"), ("varPriority", "Assign", "High"),
                            ("varAdvice", "Assign", "Move SOQL/DML out of loops and bulkify triggers fired by the batch.")], "Get_Admin_Profile")
    f.assign("Asg_Resources", [("varCategory", "Assign", "CPU or heap"), ("varPriority", "Assign", "High"),
                               ("varAdvice", "Assign", "Lower the scope size and avoid holding large collections in state.")], "Get_Admin_Profile")
    f.assign("Asg_Data", [("varCategory", "Assign", "Data validation"), ("varPriority", "Assign", "Normal"),
                          ("varAdvice", "Assign", "Fix the offending records or relax the validation rule for the integration user.")], "Get_Admin_Profile")
    f.assign("Asg_Unclassified", [("varCategory", "Assign", "Unclassified"), ("varPriority", "Assign", "Low"),
                                  ("varAdvice", "Assign", "Review the stack trace manually.")], "Get_Admin_Profile")
    admin_lookup(f, "Get_Open_Category_Tasks", "Log_Fault")
    f.get("Get_Open_Category_Tasks", "Task", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Sort_Oldest_First", "Log_Fault")
    f.sort_coll("Sort_Oldest_First", "Get_Open_Category_Tasks", "CreatedDate", "Asc", "Loop_Category_Tasks")
    f.loop("Loop_Category_Tasks", "Get_Open_Category_Tasks", "Dec_Is_Stale", "Update_Closed_Tasks", var="varCat")
    f.decision("Dec_Is_Stale", [("Stale", [("varCat.CreatedDate", "LessThan", R("fxWeekAgo"))], "Asg_Close_Stale")], "Asg_Count_Fresh", "Fresh")
    f.assign("Asg_Close_Stale", [("varCat.Status", "Assign", "Completed"), ("colToClose", "Add", R("varCat"))], "Loop_Category_Tasks")
    f.assign("Asg_Count_Fresh", [("varFreshCount", "Add", 1)], "Loop_Category_Tasks")
    f.update("Update_Closed_Tasks", input_ref="colToClose", nxt="Dec_Fresh_Exists", fault="Log_Fault")
    f.decision("Dec_Fresh_Exists", [("Fresh_Exists", [("varFreshCount", "GreaterThan", 0)], "Sub_Log_Batch_Error")], "Create_Category_Task", "None Current")
    f.create("Create_Category_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttCategory"), "OwnerId": R("Get_Admin_User.Id"),
                                              "Priority": R("varPriority"), "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Sub_Log_Batch_Error", "Log_Fault")
    f.subflow("Sub_Log_Batch_Error", "AUT_Log_Flow_Error", {"inFlowName": "BatchApexKeyword", "inErrorMessage": R("$Record.Message"),
                                                            "inRecordId": R("$Record.AsyncApexJobId"), "inSeverity": "Error",
                                                            "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Dec_Keyword", obj="BatchApexErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_namespace_stats():
    f = Flow("PEF_Flow_Error_Namespace_Stats", "PEF Flow Error Namespace Stats", "pef",
             "Subscribes to FlowExecutionErrorEvent: maintains one open statistics Task per flow namespace (count in CallDurationInSeconds, "
             "newest errors first), sums all namespace counters and e-mails an admin every 10 errors while one namespace causes 50%+ of them.")
    f.var("varTotal", "Number", scale=0, default=0)
    f.var("varMine", "Number", scale=0, default=0)
    f.var("varStat", "SObject", obj="Task")
    f.formula("fxNamespace", "String", "BLANKVALUE({!$Record.FlowNamespace}, 'local')")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Flow error stats - namespace ' & {{!fxNamespace}}, 255)")
    f.formula("fxNextCount", "Number", "BLANKVALUE({!Get_Ns_Stats.CallDurationInSeconds}, 0) + 1", scale=0)
    f.formula("fxLine", "String", "TEXT(NOW()) & ' ' & {!$Record.FlowApiName} & '/' & BLANKVALUE({!$Record.ElementApiName}, '?') & ': ' & LEFT(BLANKVALUE({!$Record.ErrorMessage}, ''), 200)")
    f.formula("fxAppended", "String", "LEFT({!fxLine} & ' || ' & BLANKVALUE({!Get_Ns_Stats.Description}, ''), 31000)")
    f.formula("fxShare", "Number", "IF({!varTotal} > 0, ROUND({!varMine} * 100 / {!varTotal}, 0), 0)", scale=0)
    f.formula("fxNotify", "Boolean", "AND({!varTotal} >= 10, {!fxShare} >= 50, MOD({!varMine}, 10) = 0)")
    f.tt("ttDominant", "Namespace {!fxNamespace} caused {!varMine} of {!varTotal} tracked flow errors ({!fxShare}%).\nLatest: {!fxLine}")
    admin_lookup(f, "Get_Ns_Stats", "Log_Fault")
    f.get("Get_Ns_Stats", "Task", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Dec_Stats_Exists", "Log_Fault", first=True)
    f.decision("Dec_Stats_Exists", [("Stats_Exist", [("Get_Ns_Stats", "IsNull", False)], "Update_Ns_Stats")], "Create_Ns_Stats", "New Namespace")
    f.update("Update_Ns_Stats", "Task", [("Id", "EqualTo", R("Get_Ns_Stats.Id"))],
             {"CallDurationInSeconds": R("fxNextCount"), "Description": R("fxAppended")}, "Get_All_Ns_Stats", "Log_Fault")
    f.create("Create_Ns_Stats", "Task", {"Subject": R("fxSubject"), "Description": R("fxLine"), "CallDurationInSeconds": 1,
                                         "OwnerId": R("Get_Admin_User.Id"), "Priority": "Low", "Status": "In Progress"}, "Get_All_Ns_Stats", "Log_Fault")
    f.get("Get_All_Ns_Stats", "Task", [("Subject", "StartsWith", PFX + "Flow error stats - namespace"), ("IsClosed", "EqualTo", False)],
          "Loop_Ns_Stats", "Log_Fault")
    f.loop("Loop_Ns_Stats", "Get_All_Ns_Stats", "Asg_Add_Total", "Dec_Dominant", var="varStat")
    f.assign("Asg_Add_Total", [("varTotal", "Add", R("varStat.CallDurationInSeconds"))], "Dec_Is_Mine")
    f.decision("Dec_Is_Mine", [("Is_Mine", [("varStat.Subject", "EqualTo", R("fxSubject"))], "Asg_Mine")], "Loop_Ns_Stats", "Other Namespace")
    f.assign("Asg_Mine", [("varMine", "Assign", R("varStat.CallDurationInSeconds"))], "Loop_Ns_Stats")
    f.decision("Dec_Dominant", [("Dominant", [("fxNotify", "EqualTo", True)], "Send_Dominant_Email")], "Sub_Log_Flow_Error", "Not Dominant")
    f.email("Send_Dominant_Email", R("Get_Admin_User.Email"), R("fxSubject"), R("ttDominant"), "Sub_Log_Flow_Error", "Log_Fault")
    f.subflow("Sub_Log_Flow_Error", "AUT_Log_Flow_Error", {"inFlowName": R("$Record.FlowApiName"), "inErrorMessage": R("fxLine"),
                                                           "inRecordId": R("$Record.InterviewGuid"), "inSeverity": "Error",
                                                           "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Get_Admin_Profile", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_process_type_router():
    f = Flow("PEF_Flow_Error_Process_Type_Router", "PEF Flow Error Process Type Router", "pef",
             "Subscribes to FlowExecutionErrorEvent: routes by ProcessType - screen flow errors become a Task for the user who ran the "
             "interview, autolaunched / Process Builder errors become one admin-owned Case per flow (recurrences raise all open Cases to High).")
    f.var("varRouteKind", "String")
    f.var("varPriority", "String")
    f.var("varTypeLabel", "String")
    f.var("varCaseCount", "Number", scale=0, default=0)
    f.var("varCase", "SObject", obj="Case")
    f.var("colCases", "SObject", coll=True, obj="Case")
    f.formula("fxCaseSubject", "String", f"LEFT('{PFX}Background flow failure: ' & {{!$Record.FlowApiName}}, 255)")
    f.formula("fxTaskSubject", "String", f"LEFT('{PFX}Your flow run failed: ' & {{!$Record.FlowApiName}}, 255)")
    f.tt("ttDetails", "Process type: {!$Record.ProcessType} ({!varTypeLabel})\nFlow: {!$Record.FlowApiName} version {!$Record.FlowVersionId}\n"
                      "Element: {!$Record.ElementApiName} ({!$Record.ElementType})\nInterview: {!$Record.InterviewGuid} started {!$Record.InterviewStartDate}\n"
                      "Error {!$Record.ExtendedErrorCode}: {!$Record.ErrorMessage}")
    f.decision("Dec_Process_Type", [
        ("Screen_Flow", [("$Record.ProcessType", "EqualTo", "Flow")], "Asg_Screen"),
        ("Autolaunched", [("$Record.ProcessType", "EqualTo", "AutoLaunchedFlow")], "Asg_Autolaunched"),
        ("Process_Builder", [("$Record.ProcessType", "EqualTo", "Workflow"), ("$Record.ProcessType", "EqualTo", "InvocableProcess"),
                             ("$Record.ProcessType", "EqualTo", "CustomEvent")], "Asg_Process_Builder", "or")],
        "Asg_Other", "Other Type")
    f.assign("Asg_Screen", [("varRouteKind", "Assign", "USER"), ("varPriority", "Assign", "Normal"), ("varTypeLabel", "Assign", "Screen flow")], "Get_Admin_Profile")
    f.assign("Asg_Autolaunched", [("varRouteKind", "Assign", "CASE"), ("varPriority", "Assign", "High"),
                                  ("varTypeLabel", "Assign", "Autolaunched / record-triggered flow")], "Get_Admin_Profile")
    f.assign("Asg_Process_Builder", [("varRouteKind", "Assign", "CASE"), ("varPriority", "Assign", "Medium"),
                                     ("varTypeLabel", "Assign", "Process Builder - plan migration to Flow")], "Get_Admin_Profile")
    f.assign("Asg_Other", [("varRouteKind", "Assign", "CASE"), ("varPriority", "Assign", "Low"), ("varTypeLabel", "Assign", "Other process type")],
             "Get_Admin_Profile")
    admin_lookup(f, "Dec_Route_Kind", "Log_Fault")
    f.decision("Dec_Route_Kind", [("User_Route", [("varRouteKind", "EqualTo", "USER"), ("$Record.InterviewStartedById", "IsNull", False)], "Create_User_Task")],
               "Get_Open_Router_Cases", "Admin Case")
    f.create("Create_User_Task", "Task", {"Subject": R("fxTaskSubject"), "Description": R("ttDetails"), "OwnerId": R("$Record.InterviewStartedById"),
                                          "Priority": R("varPriority"), "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Sub_Log_Flow_Error", "Log_Fault")
    f.get("Get_Open_Router_Cases", "Case", [("Subject", "EqualTo", R("fxCaseSubject")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("varCaseCount", "AssignCount", R("Get_Open_Router_Cases"))], "Dec_Case_Exists")
    f.decision("Dec_Case_Exists", [("Case_Exists", [("varCaseCount", "GreaterThan", 0)], "Loop_Router_Cases")], "Create_Admin_Case", "First Failure")
    f.loop("Loop_Router_Cases", "Get_Open_Router_Cases", "Asg_Raise_Priority", "Update_Router_Cases", var="varCase")
    f.assign("Asg_Raise_Priority", [("varCase.Priority", "Assign", "High"), ("colCases", "Add", R("varCase"))], "Loop_Router_Cases")
    f.update("Update_Router_Cases", input_ref="colCases", nxt="Sub_Log_Flow_Error", fault="Log_Fault")
    f.create("Create_Admin_Case", "Case", {"Subject": R("fxCaseSubject"), "Description": R("ttDetails"), "Priority": R("varPriority"),
                                           "Status": "New", "Origin": "Web", "OwnerId": R("Get_Admin_User.Id")}, "Sub_Log_Flow_Error", "Log_Fault")
    f.subflow("Sub_Log_Flow_Error", "AUT_Log_Flow_Error", {"inFlowName": R("$Record.FlowApiName"), "inErrorMessage": R("$Record.ErrorMessage"),
                                                           "inRecordId": R("$Record.InterviewGuid"), "inSeverity": "Error",
                                                           "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Dec_Process_Type", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def flow_error_user_workload():
    f = Flow("PEF_Flow_Error_Interview_User_Workload", "PEF Flow Error Interview User Workload", "pef",
             "Subscribes to FlowExecutionErrorEvent: checks the user who started the interview - if deactivated, hands their open Tasks "
             "to an admin via the bulk-reassign subflow; if active, measures open/overdue Task workload and gives the fix Task to the user "
             "or, when overloaded, to an admin.")
    f.var("varOwnerId", "String")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varOverdue", "Number", scale=0, default=0)
    f.var("varRouting", "String")
    f.var("varTask", "SObject", obj="Task")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Fix flow error: ' & {{!$Record.FlowApiName}}, 255)")
    f.tt("ttFix", "Flow {!$Record.FlowApiName} failed at {!$Record.ElementApiName} ({!$Record.ElementType}).\nError: {!$Record.ErrorMessage}\n"
                  "Interview {!$Record.InterviewGuid} started {!$Record.InterviewStartDate} by user {!$Record.InterviewStartedById}.\n"
                  "Routing: {!varRouting}\nUser workload: {!varOpenCount} open / {!varOverdue} overdue tasks.")
    f.tt("ttHandover", "User {!Get_Interview_User.Username} is deactivated but started flow {!$Record.FlowApiName}, which failed: {!$Record.ErrorMessage}\n"
                       "All of their open tasks were reassigned to you.")
    f.get("Get_Interview_User", "User", [("Id", "EqualTo", R("$Record.InterviewStartedById"))], "Get_Admin_Profile", "Log_Fault", first=True)
    admin_lookup(f, "Dec_User_State", "Log_Fault")
    f.decision("Dec_User_State", [
        ("Deactivated", [("Get_Interview_User", "IsNull", False), ("Get_Interview_User.IsActive", "EqualTo", False)], "Upd_Reassign_Open_Tasks"),
        ("Active", [("Get_Interview_User", "IsNull", False), ("Get_Interview_User.IsActive", "EqualTo", True)], "Get_User_Open_Tasks")],
        "Asg_Owner_Admin", "Unknown User")
    f.update("Upd_Reassign_Open_Tasks", "Task", [("OwnerId", "EqualTo", R("Get_Interview_User.Id")), ("IsClosed", "EqualTo", False)],
             {"OwnerId": R("Get_Admin_User.Id")}, "Create_Handover_Task", "Log_Fault")
    f.create("Create_Handover_Task", "Task", {"Subject": PFX + "Deactivated user hit a flow error - tasks handed over", "Description": R("ttHandover"),
                                              "OwnerId": R("Get_Admin_User.Id"), "Priority": "High", "Status": "Not Started",
                                              "ActivityDate": R("$Flow.CurrentDate")}, None, "Log_Fault")
    f.get("Get_User_Open_Tasks", "Task", [("OwnerId", "EqualTo", R("Get_Interview_User.Id")), ("IsClosed", "EqualTo", False)],
          "Asg_Open_Count", "Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_User_Open_Tasks"))], "Loop_User_Tasks")
    f.loop("Loop_User_Tasks", "Get_User_Open_Tasks", "Dec_Is_Overdue", "Dec_Overloaded", var="varTask")
    f.decision("Dec_Is_Overdue", [("Overdue", [("varTask.ActivityDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Count_Overdue")], "Loop_User_Tasks", "On Time")
    f.assign("Asg_Count_Overdue", [("varOverdue", "Add", 1)], "Loop_User_Tasks")
    f.decision("Dec_Overloaded", [("Overloaded", [("varOverdue", "GreaterThanOrEqualTo", 5), ("varOpenCount", "GreaterThanOrEqualTo", 25)],
                                   "Asg_Owner_Admin", "or")], "Asg_Owner_User", "Capacity OK")
    f.assign("Asg_Owner_Admin", [("varOwnerId", "Assign", R("Get_Admin_User.Id")), ("varRouting", "Assign", "admin (user overloaded or unknown)")],
             "Create_Fix_Task")
    f.assign("Asg_Owner_User", [("varOwnerId", "Assign", R("Get_Interview_User.Id")), ("varRouting", "Assign", "interview user")], "Create_Fix_Task")
    f.create("Create_Fix_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttFix"), "OwnerId": R("varOwnerId"),
                                         "Priority": "Normal", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")}, None, "Log_Fault")
    log_fault(f, severity="Error")
    f.start("Get_Interview_User", obj="FlowExecutionErrorEvent", trigger="PlatformEvent")
    return f


def status_admin_rotation():
    f = Flow("PEF_Status_Alert_Admin_Rotation", "PEF Status Alert Admin Rotation", "pef",
             "Subscribes to PlatformStatusAlertEvent: load-balances alert Tasks across all active System Administrators - counts each admin's "
             "alert Tasks created today (collection filter per admin) and assigns the new Task to the least-loaded one; e-mails on failures.")
    f.var("varAdmin", "SObject", obj="User")
    f.var("varLoad", "Number", scale=0, default=0)
    f.var("varBestLoad", "Number", scale=0, default=1000000)
    f.var("varAssigneeId", "String")
    f.var("varAssigneeEmail", "String")
    f.formula("fxToday", "DateTime", "DATETIMEVALUE(TODAY())")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Status alert: ' & BLANKVALUE({{!$Record.ServiceName}}, 'service') & ' / ' & BLANKVALUE({{!$Record.ComponentName}}, 'component'), 255)")
    f.tt("ttAlert", "Status: {!$Record.StatusType}\nSubject: {!$Record.Subject}\nService: {!$Record.ServiceName} (job {!$Record.ServiceJobId})\n"
                    "Component: {!$Record.ComponentName} / {!$Record.SubComponentName}\nAffected user: {!$Record.Username}\n"
                    "Assigned by rotation (alerts today before this one: {!varBestLoad}).")
    f.get("Get_Admin_Profile", "Profile", [("Name", "EqualTo", "System Administrator")], "Get_Active_Admins", "Log_Fault", first=True)
    f.get("Get_Active_Admins", "User", [("ProfileId", "EqualTo", R("Get_Admin_Profile.Id")), ("IsActive", "EqualTo", True)],
          "Get_Todays_Alert_Tasks", "Log_Fault", sort="CreatedDate", order="Asc")
    f.get("Get_Todays_Alert_Tasks", "Task", [("Subject", "StartsWith", PFX + "Status alert:"), ("CreatedDate", "GreaterThanOrEqualTo", R("fxToday"))],
          "Loop_Admins", "Log_Fault")
    f.loop("Loop_Admins", "Get_Active_Admins", "Filter_Admin_Tasks", "Dec_Admin_Picked", var="varAdmin")
    f.filter_coll("Filter_Admin_Tasks", "Get_Todays_Alert_Tasks", "Task", [("OwnerId", "EqualTo", R("varAdmin.Id"))], "Asg_Admin_Load")
    f.assign("Asg_Admin_Load", [("varLoad", "AssignCount", R("Filter_Admin_Tasks"))], "Dec_Lower_Load")
    f.decision("Dec_Lower_Load", [("Lower_Load", [("varLoad", "LessThan", R("varBestLoad"))], "Asg_Pick_Admin")], "Loop_Admins", "Not Lower")
    f.assign("Asg_Pick_Admin", [("varBestLoad", "Assign", R("varLoad")), ("varAssigneeId", "Assign", R("varAdmin.Id")),
                                ("varAssigneeEmail", "Assign", R("varAdmin.Email"))], "Loop_Admins")
    f.decision("Dec_Admin_Picked", [("Picked", [("varAssigneeId", "IsNull", False)], "Create_Rotation_Task")], "Sub_Log_Alert", "No Admin")
    f.create("Create_Rotation_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttAlert"), "OwnerId": R("varAssigneeId"),
                                              "Priority": "High", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Dec_Is_Failure", "Log_Fault")
    f.decision("Dec_Is_Failure", [("Failure", [("$Record.StatusType", "Contains", "Fail")], "Send_Rotation_Email")], "Sub_Log_Alert", "Not Failure")
    f.email("Send_Rotation_Email", R("varAssigneeEmail"), R("fxSubject"), R("ttAlert"), "Sub_Log_Alert", "Log_Fault")
    f.subflow("Sub_Log_Alert", "AUT_Log_Flow_Error", {"inFlowName": "PlatformStatusRotation", "inErrorMessage": R("ttAlert"),
                                                      "inRecordId": R("$Record.RequestId"), "inSeverity": "Warning", "inOwnerId": R("varAssigneeId")})
    log_fault(f, severity="Critical")
    f.start("Get_Admin_Profile", obj="PlatformStatusAlertEvent", trigger="PlatformEvent")
    return f


def status_deactivated_user():
    f = Flow("PEF_Status_Alert_Deactivated_User_Check", "PEF Status Alert Deactivated User Check", "pef",
             "Subscribes to PlatformStatusAlertEvent: checks the affected user - active users get a Task to check their integration; for "
             "inactive or unknown users it totals the open Opportunities they still own and opens an admin Case (High when pipeline is orphaned).")
    f.var("varOpp", "SObject", obj="Opportunity")
    f.var("varOppCount", "Number", scale=0, default=0)
    f.var("varOppAmount", "Currency", scale=2, default=0)
    f.var("varPriority", "String", default="Medium")
    f.formula("fxOppAmount", "Currency", "BLANKVALUE({!varOpp.Amount}, 0)", scale=2)
    f.formula("fxUserLabel", "String", "BLANKVALUE({!$Record.Username}, BLANKVALUE({!$Record.UserId}, 'unknown user'))")
    f.formula("fxCaseSubject", "String", f"LEFT('{PFX}Platform alert for inactive user ' & {{!fxUserLabel}}, 255)")
    f.tt("ttCase", "A platform status alert ({!$Record.StatusType}, API error {!$Record.ApiErrorCode}) is attributed to {!fxUserLabel}, "
                   "who is inactive or unknown.\nService: {!$Record.ServiceName} / {!$Record.ComponentName}\nSubject: {!$Record.Subject}\n"
                   "Request: {!$Record.RequestId}\nOpen opportunities still owned: {!varOppCount} worth {!varOppAmount}.\n"
                   "Check stored credentials / connected apps and reassign the pipeline.")
    f.tt("ttUserTask", "A platform status alert was raised for your session or integration.\nStatus: {!$Record.StatusType}\n"
                       "API error code: {!$Record.ApiErrorCode}\nService: {!$Record.ServiceName} / {!$Record.ComponentName}\nSubject: {!$Record.Subject}")
    f.get("Get_Alert_User", "User", [("Id", "EqualTo", R("$Record.UserId"))], "Get_Admin_Profile", "Log_Fault", first=True)
    admin_lookup(f, "Dec_User_State", "Log_Fault")
    f.decision("Dec_User_State", [("Active_User", [("Get_Alert_User", "IsNull", False), ("Get_Alert_User.IsActive", "EqualTo", True)], "Create_User_Task")],
               "Get_Owned_Open_Opps", "Inactive or Unknown")
    f.create("Create_User_Task", "Task", {"Subject": PFX + "Platform alert on your integration", "Description": R("ttUserTask"),
                                          "OwnerId": R("Get_Alert_User.Id"), "Priority": "Normal", "Status": "Not Started",
                                          "ActivityDate": R("$Flow.CurrentDate")}, "Sub_Log_Alert", "Log_Fault")
    f.get("Get_Owned_Open_Opps", "Opportunity", [("OwnerId", "EqualTo", R("$Record.UserId")), ("IsClosed", "EqualTo", False)],
          "Loop_Owned_Opps", "Log_Fault")
    f.loop("Loop_Owned_Opps", "Get_Owned_Open_Opps", "Asg_Opp_Totals", "Dec_Owns_Pipeline", var="varOpp")
    f.assign("Asg_Opp_Totals", [("varOppCount", "Add", 1), ("varOppAmount", "Add", R("fxOppAmount"))], "Loop_Owned_Opps")
    f.decision("Dec_Owns_Pipeline", [("Owns_Pipeline", [("varOppCount", "GreaterThan", 0)], "Asg_Priority_High")], "Asg_Priority_Medium", "No Pipeline")
    f.assign("Asg_Priority_High", [("varPriority", "Assign", "High")], "Create_Admin_Case")
    f.assign("Asg_Priority_Medium", [("varPriority", "Assign", "Medium")], "Create_Admin_Case")
    f.create("Create_Admin_Case", "Case", {"Subject": R("fxCaseSubject"), "Description": R("ttCase"), "Priority": R("varPriority"),
                                           "Status": "New", "Origin": "Web", "OwnerId": R("Get_Admin_User.Id")}, "Send_Admin_Email", "Log_Fault")
    f.email("Send_Admin_Email", R("Get_Admin_User.Email"), R("fxCaseSubject"), R("ttCase"), "Sub_Log_Alert", "Log_Fault")
    f.subflow("Sub_Log_Alert", "AUT_Log_Flow_Error", {"inFlowName": "PlatformStatusUserCheck", "inErrorMessage": R("$Record.Subject"),
                                                      "inRecordId": R("$Record.UserId"), "inSeverity": "Warning", "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Get_Alert_User", obj="PlatformStatusAlertEvent", trigger="PlatformEvent")
    return f


def status_component_recovery():
    f = Flow("PEF_Status_Alert_Component_Recovery", "PEF Status Alert Component Recovery", "pef",
             "Subscribes to PlatformStatusAlertEvent: tracks degraded components with one open Task per component/sub-component; a "
             "resolved/recovered/success status bulk-completes the open tracking Tasks, a new degradation opens one and e-mails an admin.")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varOpen", "SObject", obj="Task")
    f.var("colDone", "SObject", coll=True, obj="Task")
    f.formula("fxComponentKey", "String", "BLANKVALUE({!$Record.ComponentName}, 'Unknown component') & IF(ISBLANK({!$Record.SubComponentName}), '', ' / ' & {!$Record.SubComponentName})")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Component degraded: ' & {{!fxComponentKey}}, 255)")
    f.formula("fxClosingNote", "String", "LEFT(BLANKVALUE({!varOpen.Description}, '') & ' || Recovered ' & TEXT({!$Record.EventDate}) & ': ' & BLANKVALUE({!$Record.StatusType}, ''), 31000)")
    f.tt("ttDegraded", "Component {!fxComponentKey} of service {!$Record.ServiceName} reported {!$Record.StatusType} at {!$Record.EventDate}.\n"
                       "Subject: {!$Record.Subject}\nService job: {!$Record.ServiceJobId}\nRequest: {!$Record.RequestId}\nEvent: {!$Record.EventIdentifier}")
    admin_lookup(f, "Get_Open_Component_Tasks", "Log_Fault")
    f.get("Get_Open_Component_Tasks", "Task", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Component_Tasks"))], "Dec_Status_Kind")
    f.decision("Dec_Status_Kind", [("Recovered", [("$Record.StatusType", "Contains", "Resol"), ("$Record.StatusType", "Contains", "Recover"),
                                                  ("$Record.StatusType", "Contains", "Success")], "Loop_Open_Tasks", "or")],
               "Dec_Already_Tracked", "Degraded")
    f.loop("Loop_Open_Tasks", "Get_Open_Component_Tasks", "Asg_Mark_Complete", "Update_Recovered_Tasks", var="varOpen")
    f.assign("Asg_Mark_Complete", [("varOpen.Description", "Assign", R("fxClosingNote")), ("varOpen.Status", "Assign", "Completed"),
                                   ("colDone", "Add", R("varOpen"))], "Loop_Open_Tasks")
    f.update("Update_Recovered_Tasks", input_ref="colDone", nxt="Sub_Log_Alert", fault="Log_Fault")
    f.decision("Dec_Already_Tracked", [("Tracked", [("varOpenCount", "GreaterThan", 0)], "Sub_Log_Alert")], "Create_Tracking_Task", "Not Tracked")
    f.create("Create_Tracking_Task", "Task", {"Subject": R("fxSubject"), "Description": R("ttDegraded"), "OwnerId": R("Get_Admin_User.Id"),
                                              "Priority": "High", "Status": "In Progress", "ActivityDate": R("$Flow.CurrentDate")},
             "Send_Degraded_Email", "Log_Fault")
    f.email("Send_Degraded_Email", R("Get_Admin_User.Email"), R("fxSubject"), R("ttDegraded"), "Sub_Log_Alert", "Log_Fault")
    f.subflow("Sub_Log_Alert", "AUT_Log_Flow_Error", {"inFlowName": "PlatformComponentRecovery", "inErrorMessage": R("fxComponentKey"),
                                                      "inRecordId": R("$Record.ServiceJobId"), "inSeverity": "Warning",
                                                      "inOwnerId": R("Get_Admin_User.Id")})
    log_fault(f, severity="Critical")
    f.start("Get_Admin_Profile", obj="PlatformStatusAlertEvent", trigger="PlatformEvent")
    return f


ALL = [batch_phase_retry, batch_request_correlator, batch_weekly_counter, batch_keyword_classifier,
       flow_error_namespace_stats, flow_error_process_type_router, flow_error_user_workload,
       status_admin_rotation, status_deactivated_user, status_component_recovery]

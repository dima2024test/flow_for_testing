from flowlib import Flow, R, D
from common import log_fault, PFX, LOGGER


def logger():
    f = Flow(LOGGER, "AUT Log Flow Error", "auto",
             "Shared fault-path logger. Creates a '[Flow Error]' Task with throttling (max 20 per flow per hour) and "
             "e-mails the owner for Critical severity. Called from fault paths of all demo flows.")
    f.var("inFlowName", "String", inp=True)
    f.var("inErrorMessage", "String", inp=True)
    f.var("inRecordId", "String", inp=True)
    f.var("inSeverity", "String", inp=True, default="Error")
    f.var("inOwnerId", "String", inp=True)
    f.var("outLogged", "Boolean", out=True, default=False)
    f.var("outResult", "String", out=True)
    f.var("varPriority", "String")
    f.var("varNotify", "Boolean", default=False)
    f.var("varOwnerId", "String")
    f.var("varNotifyEmail", "String")
    f.var("varRecentCount", "Number", scale=0, default=0)
    f.formula("fxLastHour", "DateTime", "NOW() - (1/24)")
    f.formula("fxTaskSubject", "String", "LEFT('[Flow Error] ' & {!inFlowName} & ' (' & BLANKVALUE({!inSeverity}, 'Error') & ')', 255)")
    f.tt("ttDescription", "Flow: {!inFlowName}\nSeverity: {!inSeverity}\nRecord: {!inRecordId}\nRunning user: {!$User.Username}\n"
                          "Logged at: {!$Flow.CurrentDateTime}\n\nError message:\n{!inErrorMessage}")
    f.tt("ttEmailBody", "A critical error was logged by flow {!inFlowName}.\n\nRecord: {!inRecordId}\n\n{!inErrorMessage}")

    f.decision("Dec_Severity", [("Is_Critical", [("inSeverity", "EqualTo", "Critical")], "Asg_Critical")], "Asg_Standard", "Standard")
    f.assign("Asg_Critical", [("varPriority", "Assign", "High"), ("varNotify", "Assign", True)], "Dec_Owner_Provided")
    f.assign("Asg_Standard", [("varPriority", "Assign", "Normal"), ("varNotify", "Assign", False)], "Dec_Owner_Provided")
    f.decision("Dec_Owner_Provided", [("Owner_Provided", [("inOwnerId", "IsNull", False)], "Asg_Provided_Owner")], "Get_Running_User", "Use Running User")
    f.assign("Asg_Provided_Owner", [("varOwnerId", "Assign", R("inOwnerId"))], "Get_Recent_Logs")
    f.get("Get_Running_User", "User", [("Id", "EqualTo", R("$User.Id"))], "Dec_User_Found", "Asg_Fallback_Owner", first=True)
    f.decision("Dec_User_Found", [("User_Found", [("Get_Running_User", "IsNull", False), ("Get_Running_User.IsActive", "EqualTo", True)], "Asg_Owner_From_User")],
               "Asg_Fallback_Owner", "Not Found")
    f.assign("Asg_Owner_From_User", [("varOwnerId", "Assign", R("Get_Running_User.Id")), ("varNotifyEmail", "Assign", R("Get_Running_User.Email"))], "Get_Recent_Logs")
    f.assign("Asg_Fallback_Owner", [("varOwnerId", "Assign", R("$User.Id"))], "Get_Recent_Logs")
    f.get("Get_Recent_Logs", "Task", [("Subject", "StartsWith", "[Flow Error]"), ("Subject", "Contains", R("inFlowName")),
                                      ("CreatedDate", "GreaterThan", R("fxLastHour"))], "Asg_Count_Recent", "Create_Error_Task")
    f.assign("Asg_Count_Recent", [("varRecentCount", "AssignCount", R("Get_Recent_Logs"))], "Dec_Throttle")
    f.decision("Dec_Throttle", [("Too_Many_Logs", [("varRecentCount", "GreaterThanOrEqualTo", 20)], "Asg_Result_Skipped")], "Create_Error_Task", "Log It")
    f.create("Create_Error_Task", "Task", {"Subject": R("fxTaskSubject"), "Description": R("ttDescription"), "Priority": R("varPriority"),
                                           "Status": "Not Started", "OwnerId": R("varOwnerId"), "ActivityDate": R("$Flow.CurrentDate")},
             "Dec_Notify", "Asg_Result_Failed")
    f.decision("Dec_Notify", [("Send_Notification", [("varNotify", "EqualTo", True), ("varNotifyEmail", "IsNull", False)], "Send_Admin_Email")],
               "Asg_Result_Logged", "No Notification")
    f.email("Send_Admin_Email", R("varNotifyEmail"), R("fxTaskSubject"), R("ttEmailBody"), "Asg_Result_Logged", "Asg_Result_Logged")
    f.assign("Asg_Result_Logged", [("outLogged", "Assign", True), ("outResult", "Assign", "LOGGED")])
    f.assign("Asg_Result_Failed", [("outLogged", "Assign", False), ("outResult", "Add", R("$Flow.FaultMessage"))])
    f.assign("Asg_Result_Skipped", [("outLogged", "Assign", False), ("outResult", "Assign", "THROTTLED")])
    f.start("Dec_Severity")
    return f


def health():
    f = Flow("AUT_Account_Health_Calculator", "AUT Account Health Calculator", "auto",
             "Calculates a 0-100 health score for an Account from won/open Opportunities and open Cases and writes Hot/Warm/Cold to Account.Rating.")
    f.var("inAccountId", "String", inp=True)
    f.var("outScore", "Number", out=True, scale=0, default=0)
    f.var("outRating", "String", out=True)
    f.var("varWonAmount", "Currency", scale=2, default=0)
    f.var("varOpenPipeline", "Currency", scale=2, default=0)
    f.var("varWonCount", "Number", scale=0, default=0)
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varOpp", "SObject", obj="Opportunity")
    f.formula("fxOppAmount", "Currency", "BLANKVALUE({!varOpp.Amount}, 0)", scale=2)
    f.formula("fxScore", "Number",
              "MIN(100, MAX(0, 25 + {!varWonCount} * 10 + IF({!varOpenPipeline} > 100000, 30, IF({!varOpenPipeline} > 0, 15, 0))"
              " + IF({!varWonAmount} > 250000, 30, IF({!varWonAmount} > 0, 15, 0)) - {!varOpenCases} * 5))", scale=0)
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("inAccountId"))], "Dec_Account_Found", "Log_Fault", first=True)
    f.decision("Dec_Account_Found", [("Account_Found", [("Get_Account", "IsNull", False)], "Get_Opportunities")], "Asg_Not_Found", "Not Found")
    f.assign("Asg_Not_Found", [("outScore", "Assign", 0), ("outRating", "Assign", "Unknown")])
    f.get("Get_Opportunities", "Opportunity", [("AccountId", "EqualTo", R("inAccountId"))], "Loop_Opportunities", "Log_Fault")
    f.loop("Loop_Opportunities", "Get_Opportunities", "Dec_Opp_Status", "Get_Open_Cases", var="varOpp")
    f.decision("Dec_Opp_Status", [("Won", [("varOpp.IsWon", "EqualTo", True)], "Asg_Won"),
                                  ("Open", [("varOpp.IsClosed", "EqualTo", False)], "Asg_Open")],
               "Loop_Opportunities", "Lost")
    f.assign("Asg_Won", [("varWonAmount", "Add", R("fxOppAmount")), ("varWonCount", "Add", 1)], "Loop_Opportunities")
    f.assign("Asg_Open", [("varOpenPipeline", "Add", R("fxOppAmount"))], "Loop_Opportunities")
    f.get("Get_Open_Cases", "Case", [("AccountId", "EqualTo", R("inAccountId")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Log_Fault")
    f.assign("Asg_Case_Count", [("varOpenCases", "AssignCount", R("Get_Open_Cases"))], "Asg_Score")
    f.assign("Asg_Score", [("outScore", "Assign", R("fxScore"))], "Dec_Rating")
    f.decision("Dec_Rating", [("Hot", [("outScore", "GreaterThanOrEqualTo", 70)], "Asg_Hot"),
                              ("Warm", [("outScore", "GreaterThanOrEqualTo", 40)], "Asg_Warm")], "Asg_Cold", "Cold")
    f.assign("Asg_Hot", [("outRating", "Assign", "Hot")], "Dec_Rating_Changed")
    f.assign("Asg_Warm", [("outRating", "Assign", "Warm")], "Dec_Rating_Changed")
    f.assign("Asg_Cold", [("outRating", "Assign", "Cold")], "Dec_Rating_Changed")
    f.decision("Dec_Rating_Changed", [("Rating_Changed", [("Get_Account.Rating", "NotEqualTo", R("outRating"))], "Update_Account_Rating")], None, "Unchanged")
    f.update("Update_Account_Rating", "Account", [("Id", "EqualTo", R("inAccountId"))], {"Rating": R("outRating")}, None, "Log_Fault")
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Account")
    return f


def normalizer():
    f = Flow("AUT_Contact_Data_Normalizer", "AUT Contact Data Normalizer", "auto",
             "Copies missing mailing address / phone from the parent Account onto its Contacts (bulk update).")
    f.var("inAccountId", "String", inp=True)
    f.var("outUpdatedCount", "Number", out=True, scale=0, default=0)
    f.var("varToFixCount", "Number", scale=0, default=0)
    f.var("varContact", "SObject", obj="Contact")
    f.var("colContactsToUpdate", "SObject", coll=True, obj="Contact")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("inAccountId"))], "Dec_Account_Found", "Log_Fault", first=True)
    f.decision("Dec_Account_Found", [("Found", [("Get_Account", "IsNull", False)], "Get_Contacts")], "Asg_Nothing_To_Do", "Not Found")
    f.get("Get_Contacts", "Contact", [("AccountId", "EqualTo", R("inAccountId"))], "Filter_Contacts_Missing_Data", "Log_Fault")
    f.filter_coll("Filter_Contacts_Missing_Data", "Get_Contacts", "Contact",
                  [("MailingCity", "IsNull", True), ("Phone", "IsNull", True)], "Asg_Count_To_Fix", logic="or")
    f.assign("Asg_Count_To_Fix", [("varToFixCount", "AssignCount", R("Filter_Contacts_Missing_Data"))], "Dec_Any_To_Fix")
    f.decision("Dec_Any_To_Fix", [("Has_Contacts_To_Fix", [("varToFixCount", "GreaterThan", 0)], "Loop_Contacts")], "Asg_Nothing_To_Do", "Nothing To Fix")
    f.loop("Loop_Contacts", "Filter_Contacts_Missing_Data", "Dec_Missing_Address", "Update_Contacts", var="varContact")
    f.decision("Dec_Missing_Address", [("Address_Missing", [("varContact.MailingCity", "IsNull", True), ("Get_Account.BillingCity", "IsNull", False)], "Asg_Copy_Address")],
               "Dec_Missing_Phone", "Address OK")
    f.assign("Asg_Copy_Address", [("varContact.MailingStreet", "Assign", R("Get_Account.BillingStreet")),
                                  ("varContact.MailingCity", "Assign", R("Get_Account.BillingCity")),
                                  ("varContact.MailingPostalCode", "Assign", R("Get_Account.BillingPostalCode"))], "Dec_Missing_Phone")
    f.decision("Dec_Missing_Phone", [("Phone_Missing", [("varContact.Phone", "IsNull", True), ("Get_Account.Phone", "IsNull", False)], "Asg_Copy_Phone")],
               "Asg_Add_To_Update", "Phone OK")
    f.assign("Asg_Copy_Phone", [("varContact.Phone", "Assign", R("Get_Account.Phone"))], "Asg_Add_To_Update")
    f.assign("Asg_Add_To_Update", [("colContactsToUpdate", "Add", R("varContact")), ("outUpdatedCount", "Add", 1)], "Loop_Contacts")
    f.update("Update_Contacts", input_ref="colContactsToUpdate", fault="Log_Fault")
    f.assign("Asg_Nothing_To_Do", [("outUpdatedCount", "Assign", 0)])
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Account")
    return f


def case_wait():
    f = Flow("AUT_Case_Escalation_With_Wait", "AUT Case Escalation With Wait", "auto",
             "Raises Case priority, pauses N hours (Wait), re-checks the Case and creates an escalation Task + e-mail; retries once.")
    f.var("inCaseId", "String", inp=True)
    f.var("inHoursToWait", "Number", inp=True, scale=0, default=4)
    f.var("outStatus", "String", out=True)
    f.var("varAttempt", "Number", scale=0, default=0)
    f.var("varOriginalPriority", "String")
    f.var("varOwnerId", "String")
    f.var("varNotifyEmail", "String")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxTaskSubject", "String", f"'{PFX}Case still open after escalation (attempt ' & TEXT({{!varAttempt}}) & ')'")
    f.tt("ttEmailBody", "Case {!Get_Case_After_Wait.CaseNumber} ({!Get_Case_After_Wait.Subject}) is still open.\n"
                        "Original priority: {!varOriginalPriority}\nAttempt: {!varAttempt}")
    f.get("Get_Case", "Case", [("Id", "EqualTo", R("inCaseId"))], "Dec_Case_Open", "Log_Fault", first=True)
    f.decision("Dec_Case_Open", [("Open_Case", [("Get_Case", "IsNull", False), ("Get_Case.IsClosed", "EqualTo", False)], "Asg_Escalation_Context")],
               "Asg_Result_Skipped", "Closed or Missing")
    f.assign("Asg_Escalation_Context", [("varOriginalPriority", "Assign", R("Get_Case.Priority")), ("varAttempt", "Add", 1)], "Update_Case_Priority")
    f.update("Update_Case_Priority", "Case", [("Id", "EqualTo", R("inCaseId"))], {"Priority": "High"}, "Wait_For_Response", "Log_Fault")
    f.wait("Wait_For_Response", "After_Wait_Period", R("fxNow"), R("inHoursToWait"), "Hours", "Get_Case_After_Wait", "Log_Fault")
    f.get("Get_Case_After_Wait", "Case", [("Id", "EqualTo", R("inCaseId"))], "Dec_Still_Open", "Log_Fault", first=True)
    f.decision("Dec_Still_Open", [("Still_Open", [("Get_Case_After_Wait.IsClosed", "EqualTo", False)], "Get_Owner_User")], "Asg_Result_Resolved", "Resolved")
    f.get("Get_Owner_User", "User", [("Id", "EqualTo", R("Get_Case_After_Wait.OwnerId")), ("IsActive", "EqualTo", True)], "Dec_Owner_Is_User", "Log_Fault", first=True)
    f.decision("Dec_Owner_Is_User", [("Owner_Is_User", [("Get_Owner_User", "IsNull", False)], "Asg_Owner_User")], "Asg_Owner_Fallback", "Queue Owner")
    f.assign("Asg_Owner_User", [("varOwnerId", "Assign", R("Get_Owner_User.Id")), ("varNotifyEmail", "Assign", R("Get_Owner_User.Email"))], "Create_Escalation_Task")
    f.assign("Asg_Owner_Fallback", [("varOwnerId", "Assign", R("$User.Id")), ("varNotifyEmail", "Assign", R("$User.Email"))], "Create_Escalation_Task")
    f.create("Create_Escalation_Task", "Task", {"Subject": R("fxTaskSubject"), "WhatId": R("inCaseId"), "OwnerId": R("varOwnerId"),
                                                "Priority": "High", "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")},
             "Send_Escalation_Email", "Log_Fault")
    f.email("Send_Escalation_Email", R("varNotifyEmail"), R("fxTaskSubject"), R("ttEmailBody"), "Dec_Retry", "Log_Fault")
    f.decision("Dec_Retry", [("Retry_Again", [("varAttempt", "LessThan", 2)], "Asg_Increment_Attempt")], "Asg_Result_Escalated", "Stop")
    f.assign("Asg_Increment_Attempt", [("varAttempt", "Add", 1)], "Wait_For_Response")
    f.assign("Asg_Result_Escalated", [("outStatus", "Assign", "ESCALATED")])
    f.assign("Asg_Result_Resolved", [("outStatus", "Assign", "RESOLVED")])
    f.assign("Asg_Result_Skipped", [("outStatus", "Assign", "SKIPPED")])
    log_fault(f, record=R("inCaseId"), severity="Critical")
    f.start("Get_Case")
    return f


def opp_sequence():
    f = Flow("AUT_Opportunity_Followup_Sequence", "AUT Opportunity Followup Sequence", "auto",
             "Multi-step follow-up cadence for an open Opportunity: intro Task, wait 2 days, check progress, follow-up Task, "
             "wait 5 days, raise priority of remaining demo Tasks and notify.")
    f.var("inOpportunityId", "String", inp=True)
    f.var("outResult", "String", out=True)
    f.var("varContactId", "String")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.var("varRaisedCount", "Number", scale=0, default=0)
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxTomorrow", "Date", "TODAY() + 1")
    f.formula("fxInThreeDays", "Date", "TODAY() + 3")
    f.tt("ttSummary", "Opportunity {!Get_Opportunity.Name} has had no stage progress for 7 days.\n"
                      "Open follow-up tasks escalated: {!varRaisedCount}")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("inOpportunityId"))], "Dec_Is_Open", "Log_Fault", first=True)
    f.decision("Dec_Is_Open", [("Is_Open", [("Get_Opportunity", "IsNull", False), ("Get_Opportunity.IsClosed", "EqualTo", False)], "Get_Primary_Contact_Role")],
               "Asg_Done_Closed", "Closed")
    f.get("Get_Primary_Contact_Role", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("inOpportunityId")), ("IsPrimary", "EqualTo", True)],
          "Asg_Contact", "Log_Fault", first=True)
    f.assign("Asg_Contact", [("varContactId", "Assign", R("Get_Primary_Contact_Role.ContactId"))], "Create_Intro_Task")
    f.create("Create_Intro_Task", "Task", {"Subject": PFX + "Intro call", "WhatId": R("inOpportunityId"), "WhoId": R("varContactId"),
                                           "ActivityDate": R("fxTomorrow"), "Status": "Not Started", "Priority": "Normal"},
             "Wait_2_Days", "Log_Fault")
    f.wait("Wait_2_Days", "Two_Days_Passed", R("fxNow"), 2, "Days", "Get_Opportunity_Check", "Log_Fault")
    f.get("Get_Opportunity_Check", "Opportunity", [("Id", "EqualTo", R("inOpportunityId"))], "Dec_Stage_Progressed", "Log_Fault", first=True)
    f.decision("Dec_Stage_Progressed", [
        ("Closed_Meanwhile", [("Get_Opportunity_Check.IsClosed", "EqualTo", True)], "Asg_Done_Closed"),
        ("Stage_Changed", [("Get_Opportunity_Check.StageName", "NotEqualTo", R("Get_Opportunity.StageName"))], "Asg_Progressed")],
        "Create_Followup_Task", "No Progress")
    f.create("Create_Followup_Task", "Task", {"Subject": PFX + "Follow-up: no stage progress", "WhatId": R("inOpportunityId"),
                                              "WhoId": R("varContactId"), "ActivityDate": R("fxInThreeDays"), "Status": "Not Started", "Priority": "Normal"},
             "Wait_5_Days", "Log_Fault")
    f.wait("Wait_5_Days", "Five_Days_Passed", R("fxNow"), 5, "Days", "Get_Open_Tasks", "Log_Fault")
    f.get("Get_Open_Tasks", "Task", [("WhatId", "EqualTo", R("inOpportunityId")), ("IsClosed", "EqualTo", False), ("Subject", "StartsWith", PFX)],
          "Loop_Tasks", "Log_Fault")
    f.loop("Loop_Tasks", "Get_Open_Tasks", "Asg_Raise_Priority", "Update_Tasks", var="varTask")
    f.assign("Asg_Raise_Priority", [("varTask.Priority", "Assign", "High"), ("colTasksToUpdate", "Add", R("varTask")), ("varRaisedCount", "Add", 1)], "Loop_Tasks")
    f.update("Update_Tasks", input_ref="colTasksToUpdate", nxt="Send_Owner_Email", fault="Log_Fault")
    f.email("Send_Owner_Email", R("$User.Email"), PFX + "Opportunity needs attention", R("ttSummary"), None, "Log_Fault")
    f.assign("Asg_Progressed", [("outResult", "Assign", "PROGRESSED")])
    f.assign("Asg_Done_Closed", [("outResult", "Assign", "CLOSED")])
    log_fault(f, record=R("inOpportunityId"))
    f.start("Get_Opportunity")
    return f


ALL = [logger, health, normalizer, case_wait, opp_sequence]

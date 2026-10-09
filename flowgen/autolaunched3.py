from flowlib import Flow, R, D
from common import log_fault, PFX

LEAD_SCORE = "AUT_Lead_Score_Calculator"
WARRANTY = "AUT_Asset_Warranty_Check"
DUPES = "AUT_Account_Duplicate_Finder"
DATA_QUALITY = "AUT_Account_Data_Quality_Report"
EVENT_FOLLOWUP = "AUT_Event_Followup_Task_Creator"


# ---------------------------------------------------------------- reusable utilities (no waits)

def lead_score():
    f = Flow(LEAD_SCORE, "AUT Lead Score Calculator", "auto",
             "Campaign-free lead scoring: scores a Lead 0-100 from profile completeness, company size, lead source and logged activity, "
             "and writes Hot/Warm/Cold to Lead.Rating.")
    f.var("inLeadId", "String", inp=True)
    f.var("outScore", "Number", out=True, scale=0, default=0)
    f.var("outRating", "String", out=True)
    f.var("varActivityPoints", "Number", scale=0, default=0)
    f.var("varTask", "SObject", obj="Task")
    f.formula("fxScore", "Number",
              "MIN(100, IF(ISBLANK({!Get_Lead.Email}), 0, 15) + IF(ISBLANK({!Get_Lead.Phone}), 0, 10) + IF(ISBLANK({!Get_Lead.Title}), 0, 10)"
              " + IF(BLANKVALUE({!Get_Lead.AnnualRevenue}, 0) > 1000000, 20, IF(BLANKVALUE({!Get_Lead.AnnualRevenue}, 0) > 0, 10, 0))"
              " + IF(BLANKVALUE({!Get_Lead.NumberOfEmployees}, 0) > 200, 15, IF(BLANKVALUE({!Get_Lead.NumberOfEmployees}, 0) > 0, 5, 0))"
              " + IF(ISBLANK(TEXT({!Get_Lead.Industry})), 0, 5)"
              " + IF(TEXT({!Get_Lead.LeadSource}) = 'Partner Referral', 15, IF(TEXT({!Get_Lead.LeadSource}) = 'Web', 10, 0))"
              " + MIN(15, {!varActivityPoints}))", scale=0)
    f.get("Get_Lead", "Lead", [("Id", "EqualTo", R("inLeadId"))], "Dec_Lead_Found", "Log_Fault", first=True)
    f.decision("Dec_Lead_Found", [("Lead_Open", [("Get_Lead", "IsNull", False), ("Get_Lead.IsConverted", "EqualTo", False)], "Get_Lead_Tasks")],
               "Asg_Not_Found", "Missing or Converted")
    f.get("Get_Lead_Tasks", "Task", [("WhoId", "EqualTo", R("inLeadId"))], "Loop_Tasks", "Log_Fault")
    f.loop("Loop_Tasks", "Get_Lead_Tasks", "Dec_Task_Closed", "Asg_Score", var="varTask")
    f.decision("Dec_Task_Closed", [("Task_Done", [("varTask.IsClosed", "EqualTo", True)], "Asg_Completed_Points")], "Asg_Open_Points", "Open")
    f.assign("Asg_Completed_Points", [("varActivityPoints", "Add", 5)], "Loop_Tasks")
    f.assign("Asg_Open_Points", [("varActivityPoints", "Add", 2)], "Loop_Tasks")
    f.assign("Asg_Score", [("outScore", "Assign", R("fxScore"))], "Dec_Rating")
    f.decision("Dec_Rating", [("Score_Hot", [("outScore", "GreaterThanOrEqualTo", 70)], "Asg_Hot"),
                              ("Score_Warm", [("outScore", "GreaterThanOrEqualTo", 40)], "Asg_Warm")], "Asg_Cold", "Cold")
    f.assign("Asg_Hot", [("outRating", "Assign", "Hot")], "Dec_Rating_Changed")
    f.assign("Asg_Warm", [("outRating", "Assign", "Warm")], "Dec_Rating_Changed")
    f.assign("Asg_Cold", [("outRating", "Assign", "Cold")], "Dec_Rating_Changed")
    f.decision("Dec_Rating_Changed", [("Rating_Changed", [("Get_Lead.Rating", "NotEqualTo", R("outRating"))], "Update_Lead_Rating")], None, "Unchanged")
    f.update("Update_Lead_Rating", "Lead", [("Id", "EqualTo", R("inLeadId"))], {"Rating": R("outRating")}, None, "Log_Fault")
    f.assign("Asg_Not_Found", [("outScore", "Assign", 0), ("outRating", "Assign", "Unknown")])
    log_fault(f, record=R("inLeadId"))
    f.start("Get_Lead")
    return f


def lead_batch_scoring():
    f = Flow("AUT_Lead_Batch_Scoring", "AUT Lead Batch Scoring", "auto",
             "Re-scores a user's recent unconverted Leads (capped at the 25 newest per run) by calling AUT_Lead_Score_Calculator for each, "
             "counts Hot/Cold results and optionally e-mails a summary.")
    f.var("inOwnerId", "String", inp=True)
    f.var("inDaysBack", "Number", inp=True, scale=0, default=30)
    f.var("inNotify", "Boolean", inp=True, default=False)
    f.var("outScoredCount", "Number", out=True, scale=0, default=0)
    f.var("outHotCount", "Number", out=True, scale=0, default=0)
    f.var("outColdCount", "Number", out=True, scale=0, default=0)
    f.var("varOwnerId", "String")
    f.var("varLeadCount", "Number", scale=0, default=0)
    f.var("varRating", "String")
    f.var("varLead", "SObject", obj="Lead")
    f.formula("fxSince", "DateTime", "NOW() - BLANKVALUE({!inDaysBack}, 30)")
    f.tt("ttSummary", "Lead re-scoring finished.\nLeads scored: {!outScoredCount}\nHot: {!outHotCount}\nCold: {!outColdCount}\n"
                      "Window: last {!inDaysBack} day(s)")
    f.decision("Dec_Owner_Provided", [("Owner_Missing", [("inOwnerId", "IsNull", True), ("inOwnerId", "EqualTo", "")], "Asg_Owner_Running_User", "or")],
               "Asg_Owner_Input", "Owner Provided")
    f.assign("Asg_Owner_Input", [("varOwnerId", "Assign", R("inOwnerId"))], "Get_Open_Leads")
    f.assign("Asg_Owner_Running_User", [("varOwnerId", "Assign", R("$User.Id"))], "Get_Open_Leads")
    f.get("Get_Open_Leads", "Lead", [("OwnerId", "EqualTo", R("varOwnerId")), ("IsConverted", "EqualTo", False),
                                     ("CreatedDate", "GreaterThan", R("fxSince"))], "Asg_Lead_Count", "Log_Fault", sort="CreatedDate", order="Desc")
    f.assign("Asg_Lead_Count", [("varLeadCount", "AssignCount", R("Get_Open_Leads"))], "Dec_Has_Leads")
    f.decision("Dec_Has_Leads", [("Has_Leads", [("varLeadCount", "GreaterThan", 0)], "Sort_Newest_25")], "Asg_No_Leads", "No Leads")
    # cap: per-lead subflow call inside the loop, so only the 25 newest leads are processed per run
    f.sort_coll("Sort_Newest_25", "Get_Open_Leads", "CreatedDate", "Desc", "Loop_Leads", limit=25)
    f.loop("Loop_Leads", "Get_Open_Leads", "Sub_Score_Lead", "Dec_Notify", var="varLead")
    f.subflow("Sub_Score_Lead", LEAD_SCORE, {"inLeadId": R("varLead.Id")}, {"outRating": "varRating"}, nxt="Asg_Scored")
    f.assign("Asg_Scored", [("outScoredCount", "Add", 1)], "Dec_Rating_Result")
    f.decision("Dec_Rating_Result", [("Is_Hot", [("varRating", "EqualTo", "Hot")], "Asg_Hot"),
                                     ("Is_Cold", [("varRating", "EqualTo", "Cold")], "Asg_Cold")], "Loop_Leads", "Warm or Unknown")
    f.assign("Asg_Hot", [("outHotCount", "Add", 1)], "Loop_Leads")
    f.assign("Asg_Cold", [("outColdCount", "Add", 1)], "Loop_Leads")
    f.decision("Dec_Notify", [("Notify", [("inNotify", "EqualTo", True), ("outScoredCount", "GreaterThan", 0)], "Send_Summary_Email")], None, "No Notification")
    f.email("Send_Summary_Email", R("$User.Email"), PFX + "Lead re-scoring summary", R("ttSummary"), None, "Log_Fault")
    f.assign("Asg_No_Leads", [("outScoredCount", "Assign", 0)])
    log_fault(f, owner=R("varOwnerId"))
    f.start("Dec_Owner_Provided")
    return f


def warranty_check():
    f = Flow(WARRANTY, "AUT Asset Warranty Check", "auto",
             "Classifies an Account's Assets by UsageEndDate (expired / expiring within N days / active), returns counts and the next "
             "expiry date, and optionally creates a warranty review Task for the Account owner.")
    f.var("inAccountId", "String", inp=True)
    f.var("inDaysAhead", "Number", inp=True, scale=0, default=30)
    f.var("inCreateTask", "Boolean", inp=True, default=False)
    f.var("outExpiredCount", "Number", out=True, scale=0, default=0)
    f.var("outExpiringCount", "Number", out=True, scale=0, default=0)
    f.var("outActiveCount", "Number", out=True, scale=0, default=0)
    f.var("outNextExpiry", "Date", out=True)
    f.var("varAsset", "SObject", obj="Asset")
    f.formula("fxHorizon", "Date", "TODAY() + BLANKVALUE({!inDaysAhead}, 30)")
    f.tt("ttTaskBody", "Warranty review for {!Get_Account.Name}\nExpired assets: {!outExpiredCount}\n"
                       "Expiring within {!inDaysAhead} day(s): {!outExpiringCount}\nNext expiry: {!outNextExpiry}")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("inAccountId"))], "Dec_Account_Found", "Log_Fault", first=True)
    f.decision("Dec_Account_Found", [("Account_Found", [("Get_Account", "IsNull", False)], "Get_Assets")], "Asg_Not_Found", "Not Found")
    f.get("Get_Assets", "Asset", [("AccountId", "EqualTo", R("inAccountId")), ("UsageEndDate", "IsNull", False)], "Sort_By_End_Date", "Log_Fault")
    # sorted latest-first: the last "expiring" assignment in the loop is the earliest upcoming expiry
    f.sort_coll("Sort_By_End_Date", "Get_Assets", "UsageEndDate", "Desc", "Loop_Assets")
    f.loop("Loop_Assets", "Get_Assets", "Dec_Warranty_State", "Dec_Create_Task", var="varAsset")
    f.decision("Dec_Warranty_State", [
        ("Expired", [("varAsset.UsageEndDate", "LessThan", R("$Flow.CurrentDate"))], "Asg_Expired"),
        ("Expiring", [("varAsset.UsageEndDate", "LessThanOrEqualTo", R("fxHorizon"))], "Asg_Expiring")], "Asg_Active", "Active")
    f.assign("Asg_Expired", [("outExpiredCount", "Add", 1)], "Loop_Assets")
    f.assign("Asg_Expiring", [("outExpiringCount", "Add", 1), ("outNextExpiry", "Assign", R("varAsset.UsageEndDate"))], "Loop_Assets")
    f.assign("Asg_Active", [("outActiveCount", "Add", 1)], "Loop_Assets")
    f.decision("Dec_Create_Task", [("Task_Requested", [("inCreateTask", "EqualTo", True), ("outExpiringCount", "GreaterThan", 0)], "Create_Review_Task")],
               None, "No Task")
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Asset warranty review", "WhatId": R("inAccountId"), "OwnerId": R("Get_Account.OwnerId"),
                                            "Description": R("ttTaskBody"), "ActivityDate": R("outNextExpiry"), "Priority": "Normal",
                                            "Status": "Not Started"}, None, "Log_Fault")
    f.assign("Asg_Not_Found", [("outExpiredCount", "Assign", 0), ("outExpiringCount", "Assign", 0)])
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Account")
    return f


def duplicate_finder():
    f = Flow(DUPES, "AUT Account Duplicate Finder", "auto",
             "Finds potential duplicates of an Account by exact Name and by Phone, returns the count and a readable list of matches.")
    f.var("inAccountId", "String", inp=True)
    f.var("outDuplicateCount", "Number", out=True, scale=0, default=0)
    f.var("outDuplicateNames", "String", out=True)
    f.var("outHasDuplicates", "Boolean", out=True, default=False)
    f.var("varNameMatch", "SObject", obj="Account")
    f.var("varPhoneMatch", "SObject", obj="Account")
    f.var("colDuplicates", "SObject", coll=True, obj="Account")
    f.formula("fxNameEntry", "String", "{!varNameMatch.Name} & ' [name, ' & BLANKVALUE({!varNameMatch.BillingCity}, '-') & ']; '")
    f.formula("fxPhoneEntry", "String", "{!varPhoneMatch.Name} & ' [phone, ' & BLANKVALUE({!varPhoneMatch.BillingCity}, '-') & ']; '")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("inAccountId"))], "Dec_Account_Found", "Log_Fault", first=True)
    f.decision("Dec_Account_Found", [("Account_Found", [("Get_Account", "IsNull", False)], "Get_Name_Matches")], "Asg_Not_Found", "Not Found")
    f.get("Get_Name_Matches", "Account", [("Name", "EqualTo", R("Get_Account.Name")), ("Id", "NotEqualTo", R("inAccountId"))],
          "Loop_Name_Matches", "Log_Fault")
    f.loop("Loop_Name_Matches", "Get_Name_Matches", "Asg_Collect_Name_Match", "Dec_Has_Phone", var="varNameMatch")
    f.assign("Asg_Collect_Name_Match", [("colDuplicates", "Add", R("varNameMatch")), ("outDuplicateNames", "Add", R("fxNameEntry"))], "Loop_Name_Matches")
    f.decision("Dec_Has_Phone", [("Phone_Present", [("Get_Account.Phone", "IsNull", False)], "Get_Phone_Matches")], "Asg_Count", "No Phone")
    f.get("Get_Phone_Matches", "Account", [("Phone", "EqualTo", R("Get_Account.Phone")), ("Id", "NotEqualTo", R("inAccountId"))],
          "Filter_New_Phone_Matches", "Log_Fault")
    # skip accounts already matched by name
    f.filter_coll("Filter_New_Phone_Matches", "Get_Phone_Matches", "Account", [("Name", "NotEqualTo", R("Get_Account.Name"))], "Loop_Phone_Matches")
    f.loop("Loop_Phone_Matches", "Filter_New_Phone_Matches", "Asg_Collect_Phone_Match", "Asg_Count", var="varPhoneMatch")
    f.assign("Asg_Collect_Phone_Match", [("colDuplicates", "Add", R("varPhoneMatch")), ("outDuplicateNames", "Add", R("fxPhoneEntry"))], "Loop_Phone_Matches")
    f.assign("Asg_Count", [("outDuplicateCount", "AssignCount", R("colDuplicates"))], "Dec_Any_Duplicates")
    f.decision("Dec_Any_Duplicates", [("Duplicates_Found", [("outDuplicateCount", "GreaterThan", 0)], "Asg_Flag_Duplicates")], None, "Clean")
    f.assign("Asg_Flag_Duplicates", [("outHasDuplicates", "Assign", True)])
    f.assign("Asg_Not_Found", [("outDuplicateCount", "Assign", 0), ("outHasDuplicates", "Assign", False)])
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Account")
    return f


def data_quality_report():
    f = Flow(DATA_QUALITY, "AUT Account Data Quality Report", "auto",
             "Builds a data-quality grade (A/B/C) for an Account by combining AUT_Account_Duplicate_Finder, AUT_Asset_Warranty_Check, "
             "Contacts without e-mail and missing Account fields; optionally writes a report Task.")
    f.var("inAccountId", "String", inp=True)
    f.var("inCreateTask", "Boolean", inp=True, default=False)
    f.var("outIssueCount", "Number", out=True, scale=0, default=0)
    f.var("outQualityGrade", "String", out=True)
    f.var("outSummary", "String", out=True)
    f.var("varDuplicateCount", "Number", scale=0, default=0)
    f.var("varDuplicateNames", "String")
    f.var("varExpiredAssets", "Number", scale=0, default=0)
    f.var("varMissingEmail", "Number", scale=0, default=0)
    f.var("varContactNames", "String")
    f.var("varContact", "SObject", obj="Contact")
    f.formula("fxContactEntry", "String", "{!varContact.FirstName} & ' ' & {!varContact.LastName} & '; '")
    f.formula("fxIssues", "Number",
              "{!varDuplicateCount} + {!varExpiredAssets} + {!varMissingEmail} + IF(ISBLANK({!Get_Account.Phone}), 1, 0)"
              " + IF(ISBLANK(TEXT({!Get_Account.Industry})), 1, 0) + IF(ISBLANK({!Get_Account.BillingCity}), 1, 0)", scale=0)
    f.formula("fxSummary", "String",
              "'Grade ' & {!outQualityGrade} & ': ' & TEXT({!outIssueCount}) & ' issue(s); duplicates ' & TEXT({!varDuplicateCount})"
              " & ', expired assets ' & TEXT({!varExpiredAssets}) & ', contacts without e-mail ' & TEXT({!varMissingEmail})")
    f.tt("ttReport", "Data quality report for {!Get_Account.Name}\n{!outSummary}\n\nPossible duplicates: {!varDuplicateNames}\n"
                     "Contacts without e-mail: {!varContactNames}")
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("inAccountId"))], "Dec_Account_Found", "Log_Fault", first=True)
    f.decision("Dec_Account_Found", [("Account_Found", [("Get_Account", "IsNull", False)], "Sub_Duplicate_Check")], "Asg_Not_Found", "Not Found")
    f.subflow("Sub_Duplicate_Check", DUPES, {"inAccountId": R("inAccountId")},
              {"outDuplicateCount": "varDuplicateCount", "outDuplicateNames": "varDuplicateNames"}, nxt="Sub_Warranty_Check")
    f.subflow("Sub_Warranty_Check", WARRANTY, {"inAccountId": R("inAccountId"), "inDaysAhead": 60, "inCreateTask": False},
              {"outExpiredCount": "varExpiredAssets"}, nxt="Get_Contacts")
    f.get("Get_Contacts", "Contact", [("AccountId", "EqualTo", R("inAccountId"))], "Filter_No_Email", "Log_Fault")
    f.filter_coll("Filter_No_Email", "Get_Contacts", "Contact", [("Email", "IsNull", True)], "Loop_Contacts_No_Email")
    f.loop("Loop_Contacts_No_Email", "Filter_No_Email", "Asg_Collect_Contact", "Asg_Issue_Count", var="varContact")
    f.assign("Asg_Collect_Contact", [("varMissingEmail", "Add", 1), ("varContactNames", "Add", R("fxContactEntry"))], "Loop_Contacts_No_Email")
    f.assign("Asg_Issue_Count", [("outIssueCount", "Assign", R("fxIssues"))], "Dec_Grade")
    f.decision("Dec_Grade", [("Grade_A", [("outIssueCount", "EqualTo", 0)], "Asg_Grade_A"),
                             ("Grade_B", [("outIssueCount", "LessThanOrEqualTo", 3)], "Asg_Grade_B")], "Asg_Grade_C", "Grade C")
    f.assign("Asg_Grade_A", [("outQualityGrade", "Assign", "A")], "Asg_Summary")
    f.assign("Asg_Grade_B", [("outQualityGrade", "Assign", "B")], "Asg_Summary")
    f.assign("Asg_Grade_C", [("outQualityGrade", "Assign", "C")], "Asg_Summary")
    f.assign("Asg_Summary", [("outSummary", "Assign", R("fxSummary"))], "Dec_Create_Task")
    f.decision("Dec_Create_Task", [("Report_Requested", [("inCreateTask", "EqualTo", True), ("outIssueCount", "GreaterThan", 0)], "Create_Report_Task")],
               None, "No Task")
    f.create("Create_Report_Task", "Task", {"Subject": PFX + "Account data quality review", "WhatId": R("inAccountId"), "OwnerId": R("Get_Account.OwnerId"),
                                            "Description": R("ttReport"), "Priority": "Normal", "Status": "Not Started",
                                            "ActivityDate": R("$Flow.CurrentDate")}, None, "Log_Fault")
    f.assign("Asg_Not_Found", [("outQualityGrade", "Assign", "UNKNOWN")])
    log_fault(f, record=R("inAccountId"))
    f.start("Get_Account")
    return f


def event_followup_creator():
    f = Flow(EVENT_FOLLOWUP, "AUT Event Followup Task Creator", "auto",
             "Creates a single follow-up Task for an Event (same Who/What), skipping it when an open follow-up already exists; "
             "owner is the Event's active assignee or its creator. WhatId is left blank when the Event's WhoId is a Lead.")
    f.var("inEventId", "String", inp=True)
    f.var("inDueInDays", "Number", inp=True, scale=0, default=2)
    f.var("outTaskId", "String", out=True)
    f.var("outCreated", "Boolean", out=True, default=False)
    f.var("outResult", "String", out=True)
    f.var("varOpenFound", "Boolean", default=False)
    f.var("varOwnerId", "String")
    f.var("varTask", "SObject", obj="Task")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Follow-up: ' & {{!Get_Event.Subject}}, 255)")
    f.formula("fxDueDate", "Date", "TODAY() + BLANKVALUE({!inDueInDays}, 2)")
    f.formula("fxSince", "DateTime", "NOW() - 30")
    f.formula("fxWhoIsLead", "Boolean", "LEFT({!Get_Event.WhoId}, 3) = '00Q'")
    f.tt("ttBody", "Follow up on the meeting \"{!Get_Event.Subject}\" held {!Get_Event.StartDateTime} - {!Get_Event.EndDateTime}.\n"
                   "Location: {!Get_Event.Location}")
    f.get("Get_Event", "Event", [("Id", "EqualTo", R("inEventId"))], "Dec_Event_Found", "Log_Fault", first=True)
    f.decision("Dec_Event_Found", [("Event_Found", [("Get_Event", "IsNull", False)], "Get_Existing_Followups")], "Asg_Invalid", "Not Found")
    f.get("Get_Existing_Followups", "Task", [("Subject", "EqualTo", R("fxSubject")), ("CreatedDate", "GreaterThan", R("fxSince"))],
          "Loop_Existing", "Log_Fault")
    f.loop("Loop_Existing", "Get_Existing_Followups", "Dec_Existing_Open", "Dec_Already_Open", var="varTask")
    f.decision("Dec_Existing_Open", [("Existing_Is_Open", [("varTask.IsClosed", "EqualTo", False)], "Asg_Open_Found")], "Loop_Existing", "Closed")
    f.assign("Asg_Open_Found", [("varOpenFound", "Assign", True), ("outTaskId", "Assign", R("varTask.Id"))], "Loop_Existing")
    f.decision("Dec_Already_Open", [("Open_Followup_Exists", [("varOpenFound", "EqualTo", True)], "Asg_Exists")], "Get_Owner_User", "Create New")
    f.get("Get_Owner_User", "User", [("Id", "EqualTo", R("Get_Event.OwnerId")), ("IsActive", "EqualTo", True)], "Dec_Owner_Active", "Log_Fault", first=True)
    f.decision("Dec_Owner_Active", [("Owner_Active", [("Get_Owner_User", "IsNull", False)], "Asg_Owner_Assignee")], "Asg_Owner_Creator", "Use Creator")
    f.assign("Asg_Owner_Assignee", [("varOwnerId", "Assign", R("Get_Owner_User.Id"))], "Dec_Who_Is_Lead")
    f.assign("Asg_Owner_Creator", [("varOwnerId", "Assign", R("Get_Event.CreatedById"))], "Dec_Who_Is_Lead")
    # a Task related to a Lead (WhoId 00Q...) must not carry a WhatId
    f.decision("Dec_Who_Is_Lead", [("Who_Is_Lead", [("fxWhoIsLead", "EqualTo", True)], "Create_Lead_Followup_Task")], "Create_Followup_Task", "Contact or None")
    f.create("Create_Lead_Followup_Task", "Task", {"Subject": R("fxSubject"), "WhoId": R("Get_Event.WhoId"),
                                                   "OwnerId": R("varOwnerId"), "Description": R("ttBody"), "ActivityDate": R("fxDueDate"),
                                                   "Priority": "Normal", "Status": "Not Started"},
             "Asg_Created", "Log_Fault", id_to="outTaskId")
    f.create("Create_Followup_Task", "Task", {"Subject": R("fxSubject"), "WhoId": R("Get_Event.WhoId"), "WhatId": R("Get_Event.WhatId"),
                                              "OwnerId": R("varOwnerId"), "Description": R("ttBody"), "ActivityDate": R("fxDueDate"),
                                              "Priority": "Normal", "Status": "Not Started"},
             "Asg_Created", "Log_Fault", id_to="outTaskId")
    f.assign("Asg_Created", [("outCreated", "Assign", True), ("outResult", "Assign", "CREATED")])
    f.assign("Asg_Exists", [("outCreated", "Assign", False), ("outResult", "Assign", "ALREADY_OPEN")])
    f.assign("Asg_Invalid", [("outResult", "Assign", "EVENT_NOT_FOUND")])
    log_fault(f, record=R("inEventId"))
    f.start("Get_Event")
    return f


# ---------------------------------------------------------------- long-running flows with Wait (never call these as subflows)

def event_followup_wait():
    f = Flow("AUT_Event_Followup_With_Wait", "AUT Event Followup With Wait", "auto",
             "Waits until 1 hour after an Event ends, creates the follow-up Task via AUT_Event_Followup_Task_Creator, waits 3 days and "
             "escalates still-open follow-ups (priority High + e-mail).")
    f.var("inEventId", "String", inp=True)
    f.var("outResult", "String", out=True)
    f.var("varTaskId", "String")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasksToUpdate", "SObject", coll=True, obj="Task")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxSubject", "String", f"LEFT('{PFX}Follow-up: ' & {{!Get_Event.Subject}}, 255)")
    f.tt("ttReminder", "The follow-up for meeting \"{!Get_Event.Subject}\" is still open 3 days after the meeting.\n"
                       "Open follow-up task(s): {!varOpenCount}. Priority has been raised to High.")
    f.get("Get_Event", "Event", [("Id", "EqualTo", R("inEventId"))], "Dec_Event_Found", "Log_Fault", first=True)
    f.decision("Dec_Event_Found", [("Event_Found", [("Get_Event", "IsNull", False), ("Get_Event.EndDateTime", "IsNull", False)], "Wait_Until_Event_End")],
               "Asg_Skipped", "Not Found")
    f.wait("Wait_Until_Event_End", "One_Hour_After_End", R("Get_Event.EndDateTime"), 1, "Hours", "Get_Event_After_End", "Log_Fault")
    f.get("Get_Event_After_End", "Event", [("Id", "EqualTo", R("inEventId"))], "Dec_Event_Still_Exists", "Log_Fault", first=True)
    f.decision("Dec_Event_Still_Exists", [("Still_Exists", [("Get_Event_After_End", "IsNull", False)], "Sub_Create_Followup")], "Asg_Skipped", "Deleted")
    f.subflow("Sub_Create_Followup", EVENT_FOLLOWUP, {"inEventId": R("inEventId"), "inDueInDays": 2}, {"outTaskId": "varTaskId"}, nxt="Wait_3_Days")
    f.wait("Wait_3_Days", "Three_Days_Passed", R("fxNow"), 3, "Days", "Get_Open_Followups", "Log_Fault")
    f.get("Get_Open_Followups", "Task", [("Subject", "EqualTo", R("fxSubject")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Followups"))], "Dec_Any_Open")
    f.decision("Dec_Any_Open", [("Followups_Open", [("varOpenCount", "GreaterThan", 0)], "Loop_Open_Followups")], "Asg_Done", "All Done")
    f.loop("Loop_Open_Followups", "Get_Open_Followups", "Asg_Raise_Priority", "Update_Followups", var="varTask")
    f.assign("Asg_Raise_Priority", [("varTask.Priority", "Assign", "High"), ("colTasksToUpdate", "Add", R("varTask"))], "Loop_Open_Followups")
    f.update("Update_Followups", input_ref="colTasksToUpdate", nxt="Send_Reminder_Email", fault="Log_Fault")
    f.email("Send_Reminder_Email", R("$User.Email"), PFX + "Meeting follow-up overdue", R("ttReminder"), "Asg_Escalated", "Log_Fault")
    f.assign("Asg_Escalated", [("outResult", "Assign", "ESCALATED")])
    f.assign("Asg_Done", [("outResult", "Assign", "FOLLOWED_UP")])
    f.assign("Asg_Skipped", [("outResult", "Assign", "SKIPPED")])
    log_fault(f, record=R("inEventId"))
    f.start("Get_Event")
    return f


def contract_activation_wait():
    f = Flow("AUT_Contract_Activation_Checklist_Wait", "AUT Contract Activation Checklist Wait", "auto",
             "For a Draft Contract: checks the Account's asset warranties, creates a 3-item activation checklist (bulk Task insert), "
             "waits 7 days, then activates the Contract when all items are completed or e-mails a reminder.")
    f.var("inContractId", "String", inp=True)
    f.var("outResult", "String", out=True)
    f.var("varExpiredAssets", "Number", scale=0, default=0)
    f.var("varOpenItems", "Number", scale=0, default=0)
    f.var("varItem", "String")
    f.var("colItems", "String", coll=True)
    f.var("varNewTask", "SObject", obj="Task")
    f.var("colNewTasks", "SObject", coll=True, obj="Task")
    f.var("varCheckTask", "SObject", obj="Task")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxItemSubject", "String", f"'{PFX}Activation: ' & {{!varItem}}")
    f.formula("fxDueDate", "Date", "TODAY() + 5")
    f.tt("ttReminder", "Contract {!Get_Contract.ContractNumber} is still in Draft: {!varOpenItems} activation checklist item(s) are open.\n"
                       "Expired assets on the account: {!varExpiredAssets}")
    f.get("Get_Contract", "Contract", [("Id", "EqualTo", R("inContractId"))], "Dec_Is_Draft", "Log_Fault", first=True)
    f.decision("Dec_Is_Draft", [("Draft_Contract", [("Get_Contract", "IsNull", False), ("Get_Contract.Status", "EqualTo", "Draft")], "Sub_Warranty_Check")],
               "Asg_Skipped", "Not Draft")
    f.subflow("Sub_Warranty_Check", WARRANTY, {"inAccountId": R("Get_Contract.AccountId"), "inDaysAhead": 90, "inCreateTask": True},
              {"outExpiredCount": "varExpiredAssets"}, nxt="Asg_Checklist_Items")
    f.assign("Asg_Checklist_Items", [("colItems", "Add", "Verify signed contract document"), ("colItems", "Add", "Confirm billing contact"),
                                     ("colItems", "Add", "Schedule customer kickoff")], "Loop_Items")
    f.loop("Loop_Items", "colItems", "Asg_Build_Task", "Create_Checklist_Tasks", var="varItem")
    f.assign("Asg_Build_Task", [("varNewTask.Subject", "Assign", R("fxItemSubject")), ("varNewTask.WhatId", "Assign", R("inContractId")),
                                ("varNewTask.OwnerId", "Assign", R("Get_Contract.OwnerId")), ("varNewTask.ActivityDate", "Assign", R("fxDueDate")),
                                ("varNewTask.Status", "Assign", "Not Started"), ("varNewTask.Priority", "Assign", "Normal"),
                                ("colNewTasks", "Add", R("varNewTask"))], "Loop_Items")
    f.create("Create_Checklist_Tasks", input_ref="colNewTasks", nxt="Wait_7_Days", fault="Log_Fault")
    f.wait("Wait_7_Days", "Seven_Days_Passed", R("fxNow"), 7, "Days", "Get_Checklist_Tasks", "Log_Fault")
    f.get("Get_Checklist_Tasks", "Task", [("WhatId", "EqualTo", R("inContractId")), ("Subject", "StartsWith", PFX + "Activation:")],
          "Loop_Checklist", "Log_Fault")
    f.loop("Loop_Checklist", "Get_Checklist_Tasks", "Dec_Item_Done", "Dec_All_Done", var="varCheckTask")
    f.decision("Dec_Item_Done", [("Item_Open", [("varCheckTask.IsClosed", "EqualTo", False)], "Asg_Open_Item")], "Loop_Checklist", "Done")
    f.assign("Asg_Open_Item", [("varOpenItems", "Add", 1)], "Loop_Checklist")
    f.decision("Dec_All_Done", [("Checklist_Complete", [("varOpenItems", "EqualTo", 0)], "Update_Contract_Activated")], "Send_Reminder_Email", "Items Open")
    f.update("Update_Contract_Activated", "Contract", [("Id", "EqualTo", R("inContractId")), ("Status", "EqualTo", "Draft")],
             {"Status": "Activated"}, "Asg_Activated", "Log_Fault")
    f.email("Send_Reminder_Email", R("$User.Email"), PFX + "Contract activation checklist incomplete", R("ttReminder"), "Asg_Pending", "Log_Fault")
    f.assign("Asg_Activated", [("outResult", "Assign", "ACTIVATED")])
    f.assign("Asg_Pending", [("outResult", "Assign", "PENDING")])
    f.assign("Asg_Skipped", [("outResult", "Assign", "SKIPPED")])
    log_fault(f, record=R("inContractId"))
    f.start("Get_Contract")
    return f


def case_deflection_wait():
    f = Flow("AUT_Case_Deflection_With_Wait", "AUT Case Deflection With Wait", "auto",
             "Case deflection: for a New Case finds the 5 most recent closed Cases of the same Type, records them in a suggestion Task, "
             "waits N hours and either moves the Case to Working (not deflected) or removes the suggestion Task (deflected).")
    f.var("inCaseId", "String", inp=True)
    f.var("inHoursToWait", "Number", inp=True, scale=0, default=24)
    f.var("outResult", "String", out=True)
    f.var("varSimilarCount", "Number", scale=0, default=0)
    f.var("varSuggestions", "String")
    f.var("varEngagement", "String")
    f.var("varSuggestionTaskId", "String")
    f.var("varSimilar", "SObject", obj="Case")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxSuggestionLine", "String", "'#' & {!varSimilar.CaseNumber} & ' ' & LEFT(BLANKVALUE({!varSimilar.Subject}, '(no subject)'), 80) & '; '")
    f.tt("ttSuggestion", "Case {!Get_Case.CaseNumber} may be answered by these recently closed cases of the same type:\n{!varSuggestions}\n\n"
                         "Contact engagement: {!varEngagement}")
    f.get("Get_Case", "Case", [("Id", "EqualTo", R("inCaseId"))], "Dec_Case_New", "Log_Fault", first=True)
    f.decision("Dec_Case_New", [("New_Typed_Case", [("Get_Case", "IsNull", False), ("Get_Case.Status", "EqualTo", "New"),
                                                    ("Get_Case.Type", "IsNull", False)], "Get_Similar_Closed")], "Asg_Skipped", "Not Eligible")
    f.get("Get_Similar_Closed", "Case", [("Type", "EqualTo", R("Get_Case.Type")), ("IsClosed", "EqualTo", True), ("Id", "NotEqualTo", R("inCaseId"))],
          "Asg_Similar_Count", "Log_Fault")
    f.assign("Asg_Similar_Count", [("varSimilarCount", "AssignCount", R("Get_Similar_Closed"))], "Dec_Has_Similar")
    f.decision("Dec_Has_Similar", [("Similar_Found", [("varSimilarCount", "GreaterThan", 0)], "Sort_Recent_Five")], "Asg_Skipped", "None Found")
    f.sort_coll("Sort_Recent_Five", "Get_Similar_Closed", "ClosedDate", "Desc", "Loop_Similar", limit=5)
    f.loop("Loop_Similar", "Get_Similar_Closed", "Asg_Append_Suggestion", "Sub_Contact_Snapshot", var="varSimilar")
    f.assign("Asg_Append_Suggestion", [("varSuggestions", "Add", R("fxSuggestionLine"))], "Loop_Similar")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("Get_Case.ContactId")},
              {"outEngagement": "varEngagement"}, nxt="Create_Suggestion_Task")
    f.create("Create_Suggestion_Task", "Task", {"Subject": PFX + "Deflection suggestions", "WhatId": R("inCaseId"), "OwnerId": R("Get_Case.CreatedById"),
                                                "Description": R("ttSuggestion"), "Priority": "Normal", "Status": "Not Started",
                                                "ActivityDate": R("$Flow.CurrentDate")}, "Wait_For_Self_Service", "Log_Fault", id_to="varSuggestionTaskId")
    f.wait("Wait_For_Self_Service", "Self_Service_Window_Elapsed", R("fxNow"), R("inHoursToWait"), "Hours", "Get_Case_After_Wait", "Log_Fault")
    f.get("Get_Case_After_Wait", "Case", [("Id", "EqualTo", R("inCaseId"))], "Dec_Still_New", "Log_Fault", first=True)
    f.decision("Dec_Still_New", [("Not_Deflected", [("Get_Case_After_Wait.Status", "EqualTo", "New")], "Update_Case_Working")],
               "Delete_Suggestion_Task", "Handled")
    f.update("Update_Case_Working", "Case", [("Id", "EqualTo", R("inCaseId"))], {"Status": "Working"}, "Asg_Not_Deflected", "Log_Fault")
    f.delete("Delete_Suggestion_Task", "Task", [("Id", "EqualTo", R("varSuggestionTaskId")), ("Subject", "StartsWith", PFX), ("IsClosed", "EqualTo", False)],
             "Asg_Deflected", "Log_Fault")
    f.assign("Asg_Not_Deflected", [("outResult", "Assign", "NOT_DEFLECTED")])
    f.assign("Asg_Deflected", [("outResult", "Assign", "DEFLECTED")])
    f.assign("Asg_Skipped", [("outResult", "Assign", "SKIPPED")])
    log_fault(f, record=R("inCaseId"))
    f.start("Get_Case")
    return f


def opportunity_handoff_wait():
    f = Flow("AUT_Opportunity_Handoff_With_Wait", "AUT Opportunity Handoff With Wait", "auto",
             "Team-less handoff of a Closed Won Opportunity to an account manager: runs the Account data-quality report, waits 1 day, "
             "creates an intro Task per contact role (bulk insert), waits 7 days and reminds the new owner about open intros.")
    f.var("inOpportunityId", "String", inp=True)
    f.var("inNewOwnerId", "String", inp=True)
    f.var("outResult", "String", out=True)
    f.var("varGrade", "String")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varRole", "SObject", obj="OpportunityContactRole")
    f.var("varNewTask", "SObject", obj="Task")
    f.var("colNewTasks", "SObject", coll=True, obj="Task")
    f.formula("fxNow", "DateTime", "NOW()")
    f.formula("fxIntroSubject", "String", f"LEFT('{PFX}Handoff intro: ' & {{!Get_Opportunity.Name}}, 255)")
    f.formula("fxDueDate", "Date", "TODAY() + 3")
    f.tt("ttReminder", "You took over {!Get_Opportunity.Name} one week ago. {!varOpenCount} intro task(s) are still open.\n"
                       "Account data quality grade: {!varGrade}")
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("inOpportunityId"))], "Dec_Closed_Won", "Log_Fault", first=True)
    f.decision("Dec_Closed_Won", [("Is_Closed_Won", [("Get_Opportunity", "IsNull", False), ("Get_Opportunity.IsWon", "EqualTo", True)], "Get_New_Owner")],
               "Asg_Skipped", "Not Won")
    f.get("Get_New_Owner", "User", [("Id", "EqualTo", R("inNewOwnerId")), ("IsActive", "EqualTo", True)], "Dec_Owner_Valid", "Log_Fault", first=True)
    f.decision("Dec_Owner_Valid", [("Owner_Active", [("Get_New_Owner", "IsNull", False)], "Sub_Data_Quality")], "Asg_Skipped", "Invalid Owner")
    f.subflow("Sub_Data_Quality", DATA_QUALITY, {"inAccountId": R("Get_Opportunity.AccountId"), "inCreateTask": True},
              {"outQualityGrade": "varGrade"}, nxt="Wait_1_Day")
    f.wait("Wait_1_Day", "One_Day_Passed", R("fxNow"), 1, "Days", "Get_Contact_Roles", "Log_Fault")
    f.get("Get_Contact_Roles", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("inOpportunityId"))], "Loop_Roles", "Log_Fault")
    f.loop("Loop_Roles", "Get_Contact_Roles", "Asg_Build_Intro_Task", "Create_Intro_Tasks", var="varRole")
    f.assign("Asg_Build_Intro_Task", [("varNewTask.Subject", "Assign", R("fxIntroSubject")), ("varNewTask.WhatId", "Assign", R("inOpportunityId")),
                                      ("varNewTask.WhoId", "Assign", R("varRole.ContactId")), ("varNewTask.OwnerId", "Assign", R("inNewOwnerId")),
                                      ("varNewTask.ActivityDate", "Assign", R("fxDueDate")), ("varNewTask.Status", "Assign", "Not Started"),
                                      ("varNewTask.Priority", "Assign", "Normal"), ("colNewTasks", "Add", R("varNewTask"))], "Loop_Roles")
    f.create("Create_Intro_Tasks", input_ref="colNewTasks", nxt="Wait_7_Days", fault="Log_Fault")
    f.wait("Wait_7_Days", "Seven_Days_Passed", R("fxNow"), 7, "Days", "Get_Open_Intro_Tasks", "Log_Fault")
    f.get("Get_Open_Intro_Tasks", "Task", [("WhatId", "EqualTo", R("inOpportunityId")), ("Subject", "EqualTo", R("fxIntroSubject")),
                                           ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Intro_Tasks"))], "Dec_Any_Open")
    f.decision("Dec_Any_Open", [("Intros_Open", [("varOpenCount", "GreaterThan", 0)], "Send_Reminder_Email")], "Asg_Completed", "All Done")
    f.email("Send_Reminder_Email", R("Get_New_Owner.Email"), PFX + "Open handoff intros", R("ttReminder"), "Asg_Reminded", "Log_Fault")
    f.assign("Asg_Reminded", [("outResult", "Assign", "REMINDED")])
    f.assign("Asg_Completed", [("outResult", "Assign", "COMPLETED")])
    f.assign("Asg_Skipped", [("outResult", "Assign", "SKIPPED")])
    log_fault(f, record=R("inOpportunityId"), owner=R("inNewOwnerId"))
    f.start("Get_Opportunity")
    return f


ALL = [lead_score, lead_batch_scoring, warranty_check, duplicate_finder, data_quality_report, event_followup_creator,
       event_followup_wait, contract_activation_wait, case_deflection_wait, opportunity_handoff_wait]

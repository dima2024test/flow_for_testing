from flowlib import Flow, R, D
from common import log_fault, PFX

ERR_HTML = "<p><b>Something went wrong.</b></p><p>The error has been logged for an administrator.</p><p>{!$Flow.FaultMessage}</p>"


def error_screen(f, record=None):
    log_fault(f, name="Sub_Log_Fault", record=record, nxt="Scr_Error")
    f.screen("Scr_Error", [f.f_text("Error_Message", ERR_HTML)], allow_back=False)


def onboarding():
    f = Flow("SCR_New_Customer_Onboarding", "SCR New Customer Onboarding", "screen",
             "Wizard: capture Account details, warn about duplicate names, create Account + primary Contact (+ optional Opportunity) "
             "and show the calculated health score.")
    f.var("varAccountId", "String")
    f.var("varDuplicateCount", "Number", scale=0, default=0)
    f.var("varScore", "Number", scale=0)
    f.var("varRating", "String")
    f.formula("fxOppName", "String", f"LEFT('{PFX}' & {{!Account_Name}} & ' - New Business', 120)")
    f.formula("fxCloseDate", "Date", "TODAY() + 45")
    f.picklist_set("IndustryChoices", "Account", "Industry")
    f.choice("chContinue", "Create it anyway", "Continue")
    f.choice("chCancel", "Cancel", "Cancel")
    f.screen("Scr_Account_Details", [
        f.f_text("Intro_Text", "<p><b>New customer onboarding</b></p><p>Enter the company details.</p>"),
        f.f_input("Account_Name", "Company name", "String", required=True),
        f.f_choice("Industry_Choice", "Industry", ["IndustryChoices"], required=False),
        f.f_input("Annual_Revenue", "Annual revenue", "Currency", scale=2),
        f.f_input("Create_Opportunity", "Also create a new-business opportunity", "Boolean", default=True)],
        "Get_Duplicate_Accounts", allow_back=False)
    f.get("Get_Duplicate_Accounts", "Account", [("Name", "EqualTo", R("Account_Name"))], "Asg_Duplicate_Count", "Sub_Log_Fault")
    f.assign("Asg_Duplicate_Count", [("varDuplicateCount", "AssignCount", R("Get_Duplicate_Accounts"))], "Dec_Duplicates")
    f.decision("Dec_Duplicates", [("Duplicates_Found", [("varDuplicateCount", "GreaterThan", 0)], "Scr_Duplicate_Warning")], "Create_Account", "Unique")
    f.screen("Scr_Duplicate_Warning", [
        f.f_text("Duplicate_Text", "<p>{!varDuplicateCount} account(s) named <b>{!Account_Name}</b> already exist.</p>"),
        f.f_choice("Duplicate_Action", "What would you like to do?", ["chContinue", "chCancel"], "RadioButtons", default_choice="chCancel")],
        "Dec_User_Choice")
    f.decision("Dec_User_Choice", [("Continue_Anyway", [("Duplicate_Action", "EqualTo", "Continue")], "Create_Account")], "Scr_Cancelled", "Cancel")
    f.create("Create_Account", "Account", {"Name": R("Account_Name"), "Industry": R("Industry_Choice"), "AnnualRevenue": R("Annual_Revenue"),
                                           "Type": "Customer - Direct"}, "Scr_Contact_Details", "Sub_Log_Fault", id_to="varAccountId")
    f.screen("Scr_Contact_Details", [
        f.f_text("Contact_Intro", "<p>Primary contact for <b>{!Account_Name}</b></p>"),
        f.f_input("Contact_First_Name", "First name", "String"),
        f.f_input("Contact_Last_Name", "Last name", "String", required=True),
        f.f_input("Contact_Email", "Email", "String"),
        f.f_input("Contact_Phone", "Phone", "String")], "Create_Contact", allow_back=False)
    f.create("Create_Contact", "Contact", {"AccountId": R("varAccountId"), "FirstName": R("Contact_First_Name"), "LastName": R("Contact_Last_Name"),
                                           "Email": R("Contact_Email"), "Phone": R("Contact_Phone")}, "Dec_Create_Opportunity", "Sub_Log_Fault")
    f.decision("Dec_Create_Opportunity", [("Opportunity_Requested", [("Create_Opportunity", "EqualTo", True)], "Create_New_Opportunity")], "Sub_Health_Score", "Skip")
    f.create("Create_New_Opportunity", "Opportunity", {"Name": R("fxOppName"), "AccountId": R("varAccountId"), "StageName": "Prospecting",
                                                       "CloseDate": R("fxCloseDate"), "Amount": R("Annual_Revenue")}, "Sub_Health_Score", "Sub_Log_Fault")
    f.subflow("Sub_Health_Score", "AUT_Account_Health_Calculator", {"inAccountId": R("varAccountId")},
              {"outScore": "varScore", "outRating": "varRating"}, "Scr_Summary")
    f.screen("Scr_Summary", [f.f_text("Summary_Text", "<p><b>Done!</b></p><p>Account {!Account_Name} was created (Id {!varAccountId}).</p>"
                                                      "<p>Initial health score: {!varScore} ({!varRating})</p>")], allow_back=False)
    f.screen("Scr_Cancelled", [f.f_text("Cancelled_Text", "<p>Nothing was created.</p>")], allow_back=False)
    error_screen(f, R("varAccountId"))
    f.start("Scr_Account_Details")
    return f


def case_intake():
    f = Flow("SCR_Case_Intake_Wizard", "SCR Case Intake Wizard", "screen",
             "Support intake: find contact by e-mail (or create one), capture case details with picklist choices, bump priority for "
             "repeat customers, create Case and a follow-up Task.")
    f.var("varContactId", "String")
    f.var("varAccountId", "String")
    f.var("varCaseId", "String")
    f.var("varPriority", "String")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.formula("fxDueDate", "Date", "TODAY() + 1")
    f.picklist_set("PriorityChoices", "Case", "Priority")
    f.choice("chOriginPhone", "Phone", "Phone")
    f.choice("chOriginEmail", "Email", "Email")
    f.choice("chOriginWeb", "Web", "Web")
    f.screen("Scr_Customer_Lookup", [f.f_text("Lookup_Intro", "<p><b>Who is calling?</b></p>"),
                                     f.f_input("Customer_Email", "Customer email", "String", required=True)], "Get_Contact_By_Email", allow_back=False)
    f.get("Get_Contact_By_Email", "Contact", [("Email", "EqualTo", R("Customer_Email"))], "Dec_Contact_Found", "Sub_Log_Fault", first=True)
    f.decision("Dec_Contact_Found", [("Contact_Found", [("Get_Contact_By_Email", "IsNull", False)], "Asg_Existing_Contact")], "Scr_New_Contact", "New Customer")
    f.assign("Asg_Existing_Contact", [("varContactId", "Assign", R("Get_Contact_By_Email.Id")), ("varAccountId", "Assign", R("Get_Contact_By_Email.AccountId"))],
             "Scr_Case_Details")
    f.screen("Scr_New_Contact", [f.f_text("New_Contact_Intro", "<p>No contact found for {!Customer_Email}. Create one:</p>"),
                                 f.f_input("New_First_Name", "First name", "String"),
                                 f.f_input("New_Last_Name", "Last name", "String", required=True)], "Create_Contact")
    f.create("Create_Contact", "Contact", {"FirstName": R("New_First_Name"), "LastName": R("New_Last_Name"), "Email": R("Customer_Email")},
             "Scr_Case_Details", "Sub_Log_Fault", id_to="varContactId")
    f.screen("Scr_Case_Details", [
        f.f_input("Case_Subject", "Subject", "String", required=True),
        f.f_area("Case_Description", "Description"),
        f.f_choice("Priority_Choice", "Priority", ["PriorityChoices"]),
        f.f_choice("Origin_Choice", "Channel", ["chOriginPhone", "chOriginEmail", "chOriginWeb"], "RadioButtons", default_choice="chOriginPhone")],
        "Get_Open_Cases", allow_back=False)
    f.get("Get_Open_Cases", "Case", [("ContactId", "EqualTo", R("varContactId")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Sub_Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Cases"))], "Dec_Repeat_Customer")
    f.decision("Dec_Repeat_Customer", [("Repeat_Customer", [("varOpenCount", "GreaterThanOrEqualTo", 2)], "Asg_Bump_Priority")], "Asg_Keep_Priority", "Normal")
    f.assign("Asg_Bump_Priority", [("varPriority", "Assign", "High")], "Create_Case")
    f.assign("Asg_Keep_Priority", [("varPriority", "Assign", R("Priority_Choice"))], "Create_Case")
    f.create("Create_Case", "Case", {"ContactId": R("varContactId"), "AccountId": R("varAccountId"), "Subject": R("Case_Subject"),
                                     "Description": R("Case_Description"), "Priority": R("varPriority"), "Origin": R("Origin_Choice"), "Status": "New"},
             "Create_Followup_Task", "Sub_Log_Fault", id_to="varCaseId")
    f.create("Create_Followup_Task", "Task", {"Subject": PFX + "Follow up with customer", "WhatId": R("varCaseId"), "WhoId": R("varContactId"),
                                              "ActivityDate": R("fxDueDate"), "Priority": R("varPriority"), "Status": "Not Started"},
             "Scr_Confirmation", "Sub_Log_Fault")
    f.screen("Scr_Confirmation", [f.f_text("Confirmation_Text", "<p><b>Case created</b> (Id {!varCaseId}) with priority {!varPriority}.</p>"
                                                                "<p>The customer has {!varOpenCount} other open case(s).</p>")], allow_back=False)
    error_screen(f, R("varCaseId"))
    f.start("Scr_Customer_Lookup")
    return f


def bulk_stage():
    f = Flow("SCR_Opportunity_Bulk_Stage_Update", "SCR Opportunity Bulk Stage Update", "screen",
             "Pick an Account, then move all of its open Opportunities to a chosen stage/close date in one bulk update with an audit Task.")
    f.var("varOpp", "SObject", obj="Opportunity")
    f.var("colOppsToUpdate", "SObject", coll=True, obj="Opportunity")
    f.var("varOppCount", "Number", scale=0, default=0)
    f.var("varChanged", "Number", scale=0, default=0)
    f.formula("fxDefaultClose", "Date", "TODAY() + 30")
    f.tt("ttAudit", "Bulk stage update by {!$User.Username}: {!varChanged} opportunity(ies) moved to {!New_Stage}, close date {!New_Close_Date}.")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.picklist_set("StageChoices", "Opportunity", "StageName")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Get_Open_Opportunities", allow_back=False)
    f.get("Get_Open_Opportunities", "Opportunity", [("AccountId", "EqualTo", R("Account_Picker")), ("IsClosed", "EqualTo", False)],
          "Asg_Opp_Count", "Sub_Log_Fault", sort="CloseDate")
    f.assign("Asg_Opp_Count", [("varOppCount", "AssignCount", R("Get_Open_Opportunities"))], "Dec_Has_Opportunities")
    f.decision("Dec_Has_Opportunities", [("Has_Opportunities", [("varOppCount", "GreaterThan", 0)], "Scr_Choose_Stage")], "Scr_No_Opportunities", "None")
    f.screen("Scr_Choose_Stage", [
        f.f_text("Stage_Intro", "<p>{!varOppCount} open opportunity(ies) found.</p>"),
        f.f_choice("New_Stage", "New stage", ["StageChoices"]),
        f.f_input("New_Close_Date", "New close date", "Date", required=True, default=R("fxDefaultClose"))], "Loop_Opportunities")
    f.loop("Loop_Opportunities", "Get_Open_Opportunities", "Dec_Stage_Differs", "Dec_Anything_To_Update", var="varOpp")
    f.decision("Dec_Stage_Differs", [("Needs_Change", [("varOpp.StageName", "NotEqualTo", R("New_Stage"))], "Asg_Apply_Changes"),
                                     ("Date_Differs", [("varOpp.CloseDate", "NotEqualTo", R("New_Close_Date"))], "Asg_Apply_Changes")],
               "Loop_Opportunities", "Unchanged")
    f.assign("Asg_Apply_Changes", [("varOpp.StageName", "Assign", R("New_Stage")), ("varOpp.CloseDate", "Assign", R("New_Close_Date")),
                                   ("colOppsToUpdate", "Add", R("varOpp")), ("varChanged", "Add", 1)], "Loop_Opportunities")
    f.decision("Dec_Anything_To_Update", [("Has_Changes", [("varChanged", "GreaterThan", 0)], "Update_Opportunities")], "Scr_Result", "Nothing Changed")
    f.update("Update_Opportunities", input_ref="colOppsToUpdate", nxt="Create_Audit_Task", fault="Sub_Log_Fault")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Bulk opportunity stage update", "WhatId": R("Account_Picker"), "Description": R("ttAudit"),
                                           "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, "Scr_Result", "Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p><b>{!varChanged}</b> of {!varOppCount} opportunity(ies) updated.</p>")], allow_back=False)
    f.screen("Scr_No_Opportunities", [f.f_text("No_Opps_Text", "<p>This account has no open opportunities.</p>")])
    error_screen(f, R("Account_Picker"))
    f.start("Scr_Select_Account")
    return f


def lead_builder():
    f = Flow("SCR_Lead_To_Account_Builder", "SCR Lead To Account Builder", "screen",
             "Turns an unconverted Lead into Account (reused if the company already exists) + Contact (+ optional Opportunity), "
             "marks the Lead as working and normalizes contact data via subflow. Does not use Lead Convert.")
    f.var("varAccountId", "String")
    f.var("varContactsFixed", "Number", scale=0)
    f.formula("fxOppName", "String", f"LEFT('{PFX}' & {{!Get_Lead.Company}} & ' - From Lead', 120)")
    f.formula("fxCloseDate", "Date", "TODAY() + 60")
    f.record_set("LeadChoices", "Lead", "Name", "Id", filters=[("IsConverted", "EqualTo", False)], sort="CreatedDate", order="Desc", limit=100)
    f.screen("Scr_Select_Lead", [f.f_choice("Lead_Picker", "Lead", ["LeadChoices"])], "Get_Lead", allow_back=False)
    f.get("Get_Lead", "Lead", [("Id", "EqualTo", R("Lead_Picker"))], "Dec_Lead_Valid", "Sub_Log_Fault", first=True)
    f.decision("Dec_Lead_Valid", [("Valid", [("Get_Lead", "IsNull", False), ("Get_Lead.Company", "IsNull", False)], "Get_Existing_Account")],
               "Scr_Invalid_Lead", "Invalid")
    f.get("Get_Existing_Account", "Account", [("Name", "EqualTo", R("Get_Lead.Company"))], "Dec_Account_Exists", "Sub_Log_Fault", first=True)
    f.decision("Dec_Account_Exists", [("Exists", [("Get_Existing_Account", "IsNull", False)], "Asg_Use_Existing_Account")], "Create_Account", "Create New")
    f.assign("Asg_Use_Existing_Account", [("varAccountId", "Assign", R("Get_Existing_Account.Id"))], "Scr_Review")
    f.create("Create_Account", "Account", {"Name": R("Get_Lead.Company"), "Industry": R("Get_Lead.Industry"), "Phone": R("Get_Lead.Phone"),
                                           "Website": R("Get_Lead.Website"), "AccountSource": R("Get_Lead.LeadSource"), "Type": "Prospect"},
             "Scr_Review", "Sub_Log_Fault", id_to="varAccountId")
    f.screen("Scr_Review", [
        f.f_text("Review_Text", "<p>Lead <b>{!Get_Lead.FirstName} {!Get_Lead.LastName}</b> will be added as a contact to account {!varAccountId}.</p>"),
        f.f_input("Create_Opp", "Create an opportunity", "Boolean", default=False),
        f.f_input("Opp_Amount", "Opportunity amount", "Currency", scale=2)], "Create_Contact")
    f.create("Create_Contact", "Contact", {"AccountId": R("varAccountId"), "FirstName": R("Get_Lead.FirstName"), "LastName": R("Get_Lead.LastName"),
                                           "Email": R("Get_Lead.Email"), "Phone": R("Get_Lead.Phone"), "Title": R("Get_Lead.Title"),
                                           "LeadSource": R("Get_Lead.LeadSource")}, "Dec_Create_Opp", "Sub_Log_Fault")
    f.decision("Dec_Create_Opp", [("Opp_Requested", [("Create_Opp", "EqualTo", True)], "Create_Opportunity")], "Update_Lead", "No Opportunity")
    f.create("Create_Opportunity", "Opportunity", {"Name": R("fxOppName"), "AccountId": R("varAccountId"), "StageName": "Qualification",
                                                   "CloseDate": R("fxCloseDate"), "Amount": R("Opp_Amount"), "LeadSource": R("Get_Lead.LeadSource")},
             "Update_Lead", "Sub_Log_Fault")
    f.update("Update_Lead", "Lead", [("Id", "EqualTo", R("Lead_Picker"))], {"Status": "Working - Contacted"}, "Sub_Normalize_Contacts", "Sub_Log_Fault")
    f.subflow("Sub_Normalize_Contacts", "AUT_Contact_Data_Normalizer", {"inAccountId": R("varAccountId")}, {"outUpdatedCount": "varContactsFixed"}, "Scr_Done")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Done.</b> Account {!varAccountId} is ready; {!varContactsFixed} contact(s) normalized.</p>")], allow_back=False)
    f.screen("Scr_Invalid_Lead", [f.f_text("Invalid_Text", "<p>The selected lead has no company and cannot be used.</p>")])
    error_screen(f, R("Lead_Picker"))
    f.start("Scr_Select_Lead")
    return f


def task_planner():
    f = Flow("SCR_Account_Task_Planner", "SCR Account Task Planner", "screen",
             "Pick an Account and plan a Task for each of its contacts (optionally only those with an e-mail), built in a loop and "
             "inserted in one bulk create.")
    f.var("varContact", "SObject", obj="Contact")
    f.var("colTargets", "SObject", coll=True, obj="Contact")
    f.var("varTask", "SObject", obj="Task")
    f.var("colTasks", "SObject", coll=True, obj="Task")
    f.var("varContactCount", "Number", scale=0, default=0)
    f.var("varTaskCount", "Number", scale=0, default=0)
    f.formula("fxTaskSubject", "String", f"LEFT('{PFX}' & {{!Task_Subject}} & ' - ' & {{!varContact.LastName}}, 255)")
    f.formula("fxDueDate", "Date", "TODAY() + {!Days_Until_Due}")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.picklist_set("TaskPriorityChoices", "Task", "Priority")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Get_Account_Contacts", allow_back=False)
    f.get("Get_Account_Contacts", "Contact", [("AccountId", "EqualTo", R("Account_Picker"))], "Asg_Contact_Count", "Sub_Log_Fault", sort="LastName")
    f.assign("Asg_Contact_Count", [("varContactCount", "AssignCount", R("Get_Account_Contacts"))], "Dec_Has_Contacts")
    f.decision("Dec_Has_Contacts", [("Has_Contacts", [("varContactCount", "GreaterThan", 0)], "Scr_Plan_Details")], "Scr_No_Contacts", "No Contacts")
    f.screen("Scr_Plan_Details", [
        f.f_text("Plan_Intro", "<p>{!varContactCount} contact(s) on this account.</p>"),
        f.f_input("Task_Subject", "Task subject", "String", required=True),
        f.f_input("Days_Until_Due", "Due in (days)", "Number", required=True, scale=0, default=7),
        f.f_choice("Task_Priority", "Priority", ["TaskPriorityChoices"]),
        f.f_input("Only_With_Email", "Only contacts with an email", "Boolean", default=False)], "Dec_Filter_Option")
    f.decision("Dec_Filter_Option", [("Email_Only", [("Only_With_Email", "EqualTo", True)], "Filter_Contacts_With_Email")], "Asg_Use_All", "All Contacts")
    f.filter_coll("Filter_Contacts_With_Email", "Get_Account_Contacts", "Contact", [("Email", "IsNull", False)], "Asg_Use_Filtered")
    f.assign("Asg_Use_Filtered", [("colTargets", "Assign", R("Filter_Contacts_With_Email"))], "Loop_Targets")
    f.assign("Asg_Use_All", [("colTargets", "Assign", R("Get_Account_Contacts"))], "Loop_Targets")
    f.loop("Loop_Targets", "colTargets", "Asg_Build_Task", "Dec_Any_Tasks", var="varContact")
    f.assign("Asg_Build_Task", [("varTask.Subject", "Assign", R("fxTaskSubject")), ("varTask.WhoId", "Assign", R("varContact.Id")),
                                ("varTask.WhatId", "Assign", R("Account_Picker")), ("varTask.ActivityDate", "Assign", R("fxDueDate")),
                                ("varTask.Priority", "Assign", R("Task_Priority")), ("varTask.Status", "Assign", "Not Started"),
                                ("colTasks", "Add", R("varTask")), ("varTaskCount", "Add", 1)], "Loop_Targets")
    f.decision("Dec_Any_Tasks", [("Has_Tasks", [("varTaskCount", "GreaterThan", 0)], "Create_Tasks")], "Scr_Result", "No Tasks")
    f.create("Create_Tasks", input_ref="colTasks", nxt="Scr_Result", fault="Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p><b>{!varTaskCount}</b> task(s) created.</p>")], allow_back=False)
    f.screen("Scr_No_Contacts", [f.f_text("No_Contacts_Text", "<p>This account has no contacts.</p>")])
    error_screen(f, R("Account_Picker"))
    f.start("Scr_Select_Account")
    return f


ALL = [onboarding, case_intake, bulk_stage, lead_builder, task_planner]

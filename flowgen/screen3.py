from flowlib import Flow, R, D
from common import log_fault, PFX
from screen import error_screen


def asset_registration():
    f = Flow("SCR_Asset_Registration_Wizard", "SCR Asset Registration Wizard", "screen",
             "Register a customer Asset: pick Account and (optional) Contact, enter serial/price/dates, warn about duplicate serial "
             "numbers, create the Asset (+ optional install Task) and show the account's installed base sorted by value.")
    f.var("varAssetId", "String")
    f.var("varAsset", "SObject", obj="Asset")
    f.var("varDupCount", "Number", scale=0, default=0)
    f.var("varAssetCount", "Number", scale=0, default=0)
    f.var("varBaseValue", "Currency", scale=2, default=0)
    f.var("varTopAssets", "String", default="")
    f.formula("fxAssetName", "String", f"LEFT('{PFX}' & {{!Asset_Name}}, 255)")
    f.formula("fxInstallDue", "Date", "BLANKVALUE({!Install_Date}, TODAY() + 7)")
    f.formula("fxAssetValue", "Currency", "BLANKVALUE({!varAsset.Price}, 0) * BLANKVALUE({!varAsset.Quantity}, 1)", scale=2)
    f.formula("fxAssetLine", "String", "{!varAsset.Name} & ' [' & BLANKVALUE(TEXT({!varAsset.Status}), 'n/a') & '] ' & TEXT({!fxAssetValue}) & '; '")
    f.tt("ttInstall", "Install asset {!fxAssetName} (serial {!Serial_Number}) for the customer. Purchased {!Purchase_Date}.")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.record_set("ContactChoices", "Contact", "Name", "Id", filters=[("AccountId", "EqualTo", R("Account_Picker"))], sort="LastName")
    f.picklist_set("AssetStatusChoices", "Asset", "Status")
    f.screen("Scr_Select_Account", [
        f.f_text("Intro_Text", "<p><b>Register a new asset</b></p><p>Choose the owning account.</p>"),
        f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Scr_Asset_Details", allow_back=False)
    f.screen("Scr_Asset_Details", [
        f.f_choice("Contact_Picker", "Contact (optional)", ["ContactChoices"], required=False),
        f.f_input("Asset_Name", "Asset / product name", "String", required=True),
        f.f_input("Serial_Number", "Serial number", "String", required=True),
        f.f_choice("Asset_Status", "Status", ["AssetStatusChoices"]),
        f.f_input("Asset_Price", "Price", "Currency", scale=2),
        f.f_input("Asset_Quantity", "Quantity", "Number", scale=0, default=1),
        f.f_input("Purchase_Date", "Purchase date", "Date", default=R("$Flow.CurrentDate")),
        f.f_input("Install_Date", "Install date", "Date"),
        f.f_input("Competitor_Product", "Competitor product", "Boolean", default=False),
        f.f_input("Schedule_Install", "Create an installation task", "Boolean", default=True)], "Get_Serial_Duplicates")
    f.get("Get_Serial_Duplicates", "Asset", [("SerialNumber", "EqualTo", R("Serial_Number"))], "Asg_Dup_Count", "Sub_Log_Fault")
    f.assign("Asg_Dup_Count", [("varDupCount", "AssignCount", R("Get_Serial_Duplicates"))], "Dec_Duplicate_Serial")
    f.decision("Dec_Duplicate_Serial", [("Serial_Exists", [("varDupCount", "GreaterThan", 0)], "Scr_Duplicate_Serial")], "Create_Asset", "Unique")
    f.screen("Scr_Duplicate_Serial", [f.f_text("Duplicate_Text", "<p>Serial number <b>{!Serial_Number}</b> is already registered on "
                                                                 "{!varDupCount} asset(s). Go back and correct it.</p>")])
    f.create("Create_Asset", "Asset", {"Name": R("fxAssetName"), "AccountId": R("Account_Picker"), "ContactId": R("Contact_Picker"),
                                       "SerialNumber": R("Serial_Number"), "Status": R("Asset_Status"), "Price": R("Asset_Price"),
                                       "Quantity": R("Asset_Quantity"), "PurchaseDate": R("Purchase_Date"), "InstallDate": R("Install_Date"),
                                       "IsCompetitorProduct": R("Competitor_Product")}, "Dec_Install_Task", "Sub_Log_Fault", id_to="varAssetId")
    f.decision("Dec_Install_Task", [("Install_Requested", [("Schedule_Install", "EqualTo", True)], "Create_Install_Task")], "Get_Account_Assets", "No Task")
    f.create("Create_Install_Task", "Task", {"Subject": PFX + "Install asset", "WhatId": R("varAssetId"), "WhoId": R("Contact_Picker"),
                                             "ActivityDate": R("fxInstallDue"), "Description": R("ttInstall"), "Priority": "Normal",
                                             "Status": "Not Started"}, "Get_Account_Assets", "Sub_Log_Fault")
    f.get("Get_Account_Assets", "Asset", [("AccountId", "EqualTo", R("Account_Picker"))], "Sort_Assets", "Sub_Log_Fault")
    f.sort_coll("Sort_Assets", "Get_Account_Assets", "Price", "Desc", "Loop_Assets")
    f.loop("Loop_Assets", "Get_Account_Assets", "Asg_Tally_Asset", "Scr_Summary", var="varAsset")
    f.assign("Asg_Tally_Asset", [("varAssetCount", "Add", 1), ("varBaseValue", "Add", R("fxAssetValue")), ("varTopAssets", "Add", R("fxAssetLine"))],
             "Loop_Assets")
    f.screen("Scr_Summary", [f.f_text("Summary_Text", "<p><b>Asset registered</b> (Id {!varAssetId}).</p>"
                                                      "<p>Installed base: {!varAssetCount} asset(s), total value {!varBaseValue}.</p><p>{!varTopAssets}</p>")],
             allow_back=False)
    error_screen(f, R("varAssetId"))
    f.start("Scr_Select_Account")
    return f


def contract_wizard():
    f = Flow("SCR_Contract_Creation_Wizard", "SCR Contract Creation Wizard", "screen",
             "Create a Contract for an Account: checks overlapping activated contracts, lets the user proceed or cancel, creates a "
             "Draft contract, optionally activates it and creates a countersignature Task.")
    f.var("varContract", "SObject", obj="Contract")
    f.var("varContractId", "String")
    f.var("varOverlaps", "Number", scale=0, default=0)
    f.var("varOverlapList", "String", default="")
    f.formula("fxContractName", "String", f"LEFT('{PFX}' & 'Contract from ' & TEXT({{!Contract_Start}}), 80)")
    f.formula("fxContractLine", "String", "{!varContract.ContractNumber} & ' (ends ' & TEXT({!varContract.EndDate}) & '); '")
    f.formula("fxSignDue", "Date", "TODAY() + 5")
    f.tt("ttSign", "Get contract {!varContractId} countersigned. Term: {!Contract_Term} month(s) from {!Contract_Start}. Special terms: {!Special_Terms}")
    f.choice("chProceed", "Create it anyway", "Proceed")
    f.choice("chCancel", "Cancel", "Cancel")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.record_set("SignerChoices", "Contact", "Name", "Id", filters=[("AccountId", "EqualTo", R("Account_Picker"))], sort="LastName")
    f.screen("Scr_Select_Account", [f.f_text("Intro_Text", "<p><b>New contract</b></p>"),
                                    f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Scr_Contract_Terms", allow_back=False)
    f.screen("Scr_Contract_Terms", [
        f.f_input("Contract_Start", "Start date", "Date", required=True, default=R("$Flow.CurrentDate")),
        f.f_input("Contract_Term", "Term (months)", "Number", required=True, scale=0, default=12),
        f.f_choice("Signer_Picker", "Customer signed by", ["SignerChoices"], required=False),
        f.f_input("Signed_Date", "Customer signed date", "Date"),
        f.f_area("Special_Terms", "Special terms"),
        f.f_input("Activate_Now", "Activate immediately", "Boolean", default=False)], "Get_Active_Contracts")
    f.get("Get_Active_Contracts", "Contract", [("AccountId", "EqualTo", R("Account_Picker")), ("Status", "EqualTo", "Activated")],
          "Loop_Contracts", "Sub_Log_Fault", sort="EndDate")
    f.loop("Loop_Contracts", "Get_Active_Contracts", "Dec_Overlaps", "Dec_Has_Overlap", var="varContract")
    f.decision("Dec_Overlaps", [("Overlaps", [("varContract.EndDate", "GreaterThanOrEqualTo", R("Contract_Start"))], "Asg_Overlap")],
               "Loop_Contracts", "No Overlap")
    f.assign("Asg_Overlap", [("varOverlaps", "Add", 1), ("varOverlapList", "Add", R("fxContractLine"))], "Loop_Contracts")
    f.decision("Dec_Has_Overlap", [("Has_Overlap", [("varOverlaps", "GreaterThan", 0)], "Scr_Overlap_Warning")], "Create_Contract", "Clear")
    f.screen("Scr_Overlap_Warning", [
        f.f_text("Overlap_Text", "<p>{!varOverlaps} activated contract(s) still run on/after the new start date:</p><p>{!varOverlapList}</p>"),
        f.f_choice("Overlap_Action", "What would you like to do?", ["chProceed", "chCancel"], "RadioButtons", default_choice="chCancel")],
        "Dec_Proceed")
    f.decision("Dec_Proceed", [("Proceed", [("Overlap_Action", "EqualTo", "Proceed")], "Create_Contract")], "Scr_Cancelled", "Cancel")
    f.create("Create_Contract", "Contract", {"Name": R("fxContractName"), "AccountId": R("Account_Picker"), "StartDate": R("Contract_Start"),
                                             "ContractTerm": R("Contract_Term"), "CustomerSignedId": R("Signer_Picker"),
                                             "CustomerSignedDate": R("Signed_Date"), "SpecialTerms": R("Special_Terms"), "Status": "Draft"},
             "Dec_Activate", "Sub_Log_Fault", id_to="varContractId")
    f.decision("Dec_Activate", [("Activate", [("Activate_Now", "EqualTo", True)], "Update_Activate_Contract")], "Create_Countersign_Task", "Keep Draft")
    f.update("Update_Activate_Contract", "Contract", [("Id", "EqualTo", R("varContractId"))], {"Status": "Activated"},
             "Create_Countersign_Task", "Sub_Log_Fault")
    f.create("Create_Countersign_Task", "Task", {"Subject": PFX + "Countersign contract", "WhatId": R("varContractId"), "Description": R("ttSign"),
                                                 "ActivityDate": R("fxSignDue"), "Priority": "High", "Status": "Not Started"}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Contract created</b> (Id {!varContractId}). A countersignature task was added.</p>")],
             allow_back=False)
    f.screen("Scr_Cancelled", [f.f_text("Cancelled_Text", "<p>No contract was created.</p>")], allow_back=False)
    error_screen(f, R("varContractId"))
    f.start("Scr_Select_Account")
    return f


def event_rescheduler():
    f = Flow("SCR_Event_Rescheduler", "SCR Event Rescheduler", "screen",
             "Pick one of my upcoming Events, choose a new start/duration and reason, detect calendar conflicts, update the Event, "
             "optionally e-mail the attendee and log a completed Task.")
    f.var("varOverlap", "SObject", obj="Event")
    f.var("varConflicts", "Number", scale=0, default=0)
    f.var("varConflictList", "String", default="")
    f.formula("fxNewEnd", "DateTime", "{!New_Start} + ({!New_Duration} / 1440)")
    f.formula("fxConflictLine", "String", "BLANKVALUE({!varOverlap.Subject}, '(no subject)') & ' @ ' & TEXT({!varOverlap.StartDateTime}) & '; '")
    f.formula("fxDescription", "String", "LEFT(BLANKVALUE({!Get_Event.Description}, '') & ' | Rescheduled (' & {!Reschedule_Reason} & '): ' "
                                         "& BLANKVALUE({!Reschedule_Comment}, ''), 32000)")
    f.formula("fxEmailSubject", "String", "'Rescheduled: ' & BLANKVALUE({!Get_Event.Subject}, 'meeting')")
    f.tt("ttEmail", "Hello,\n\nour meeting \"{!Get_Event.Subject}\" has been moved to {!New_Start} ({!New_Duration} minutes).\n"
                    "Reason: {!Reschedule_Reason}\n{!Reschedule_Comment}\n\nBest regards,\n{!$User.FirstName} {!$User.LastName}")
    f.tt("ttLog", "Event {!Event_Picker} moved from {!Get_Event.StartDateTime} to {!New_Start}. Reason: {!Reschedule_Reason}. Conflicts: {!varConflictList}")
    f.choice("chCustomer", "Customer request", "Customer request")
    f.choice("chConflict", "Internal conflict", "Internal conflict")
    f.choice("chTravel", "Travel / logistics", "Travel")
    f.choice("chProceed", "Move it anyway", "Proceed")
    f.choice("chCancel", "Cancel", "Cancel")
    f.record_set("EventChoices", "Event", "Subject", "Id", filters=[("OwnerId", "EqualTo", R("$User.Id")),
                                                                    ("StartDateTime", "GreaterThan", R("$Flow.CurrentDateTime")),
                                                                    ("IsAllDayEvent", "EqualTo", False)],
                 sort="StartDateTime", limit=100)
    f.screen("Scr_Select_Event", [f.f_text("Intro_Text", "<p><b>Reschedule a meeting</b></p>"),
                                  f.f_choice("Event_Picker", "Upcoming event", ["EventChoices"])], "Get_Event", allow_back=False)
    f.get("Get_Event", "Event", [("Id", "EqualTo", R("Event_Picker"))], "Scr_New_Time", "Sub_Log_Fault", first=True)
    f.screen("Scr_New_Time", [
        f.f_text("Current_Text", "<p>Currently: <b>{!Get_Event.Subject}</b> at {!Get_Event.StartDateTime}</p>"),
        f.f_input("New_Start", "New start", "DateTime", required=True),
        f.f_input("New_Duration", "Duration (minutes)", "Number", required=True, scale=0, default=R("Get_Event.DurationInMinutes")),
        f.f_choice("Reschedule_Reason", "Reason", ["chCustomer", "chConflict", "chTravel"], default_choice="chCustomer"),
        f.f_area("Reschedule_Comment", "Comment"),
        f.f_input("Attendee_Email", "Notify attendee (email, optional)", "String")], "Dec_Valid_Time")
    f.decision("Dec_Valid_Time", [("Invalid_Time", [("New_Duration", "LessThanOrEqualTo", 0), ("New_Start", "LessThan", R("$Flow.CurrentDateTime"))],
                                   "Scr_Invalid", "or")], "Get_Overlapping_Events", "Valid")
    f.get("Get_Overlapping_Events", "Event", [("OwnerId", "EqualTo", R("$User.Id")), ("StartDateTime", "LessThan", R("fxNewEnd")),
                                              ("EndDateTime", "GreaterThan", R("New_Start")), ("Id", "NotEqualTo", R("Event_Picker"))],
          "Loop_Overlaps", "Sub_Log_Fault", sort="StartDateTime")
    f.loop("Loop_Overlaps", "Get_Overlapping_Events", "Asg_Conflict", "Dec_Conflict", var="varOverlap")
    f.assign("Asg_Conflict", [("varConflicts", "Add", 1), ("varConflictList", "Add", R("fxConflictLine"))], "Loop_Overlaps")
    f.decision("Dec_Conflict", [("Has_Conflict", [("varConflicts", "GreaterThan", 0)], "Scr_Conflict")], "Update_Event", "Free")
    f.screen("Scr_Conflict", [f.f_text("Conflict_Text", "<p>The new slot overlaps {!varConflicts} event(s):</p><p>{!varConflictList}</p>"),
                              f.f_choice("Conflict_Action", "What would you like to do?", ["chProceed", "chCancel"], "RadioButtons",
                                         default_choice="chCancel")], "Dec_Proceed")
    f.decision("Dec_Proceed", [("Proceed", [("Conflict_Action", "EqualTo", "Proceed")], "Update_Event")], "Scr_Cancelled", "Cancel")
    f.update("Update_Event", "Event", [("Id", "EqualTo", R("Event_Picker"))],
             {"StartDateTime": R("New_Start"), "EndDateTime": R("fxNewEnd"), "Description": R("fxDescription")}, "Dec_Notify", "Sub_Log_Fault")
    f.decision("Dec_Notify", [("Notify", [("Attendee_Email", "IsNull", False)], "Email_Attendee")], "Create_Log_Task", "No Email")
    f.email("Email_Attendee", R("Attendee_Email"), R("fxEmailSubject"), R("ttEmail"), "Create_Log_Task", "Sub_Log_Fault")
    f.create("Create_Log_Task", "Task", {"Subject": PFX + "Meeting rescheduled", "WhoId": R("Get_Event.WhoId"), "WhatId": R("Get_Event.WhatId"),
                                         "Description": R("ttLog"), "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")},
             "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Rescheduled</b> to {!New_Start}.</p>")], allow_back=False)
    f.screen("Scr_Invalid", [f.f_text("Invalid_Text", "<p>Start must be in the future and duration greater than 0. Go back and fix it.</p>")])
    f.screen("Scr_Cancelled", [f.f_text("Cancelled_Text", "<p>The event was not changed.</p>")], allow_back=False)
    error_screen(f, R("Event_Picker"))
    f.start("Scr_Select_Event")
    return f


def bant_survey():
    f = Flow("SCR_Lead_BANT_Qualification", "SCR Lead BANT Qualification", "screen",
             "BANT survey for an open Lead: Budget/Authority/Need/Timeline answers produce a 0-100 score, set Rating/Status and a "
             "summary on the Lead, optionally copy the rating to other open leads of the same company, create a call Task for hot leads.")
    f.var("varRating", "String")
    f.var("varStatus", "String")
    f.var("varSibling", "SObject", obj="Lead")
    f.var("colSiblings", "SObject", coll=True, obj="Lead")
    f.var("varSiblingCount", "Number", scale=0, default=0)
    f.formula("fxBantScore", "Number", "VALUE({!Budget_Answer}) + VALUE({!Authority_Answer}) + VALUE({!Need_Answer}) + VALUE({!Timeline_Answer})",
              scale=0)
    f.formula("fxCallDate", "Date", "TODAY() + 1")
    f.tt("ttBant", "BANT score {!fxBantScore}/100 ({!varRating}) on {!$Flow.CurrentDate} by {!$User.Username}\n"
                   "Budget points: {!Budget_Answer}, expected budget {!Expected_Budget}\nAuthority points: {!Authority_Answer}\n"
                   "Need points: {!Need_Answer}\nTimeline points: {!Timeline_Answer}, decision by {!Decision_Date}\nNotes: {!Bant_Notes}")
    for n, t, v in [("chBudgetApproved", "Approved budget", "30"), ("chBudgetPlanned", "Budget being planned", "15"), ("chBudgetNone", "No budget", "0"),
                    ("chAuthDecider", "Decision maker", "25"), ("chAuthInfluencer", "Influencer", "15"), ("chAuthUser", "End user / no authority", "5"),
                    ("chNeedCritical", "Critical business need", "25"), ("chNeedNice", "Nice to have", "10"), ("chNeedNone", "No clear need", "0"),
                    ("chTime3", "Within 3 months", "20"), ("chTime6", "3 to 6 months", "10"), ("chTimeLater", "Later / unknown", "0")]:
        f.choice(n, t, v)
    f.record_set("LeadChoices", "Lead", "Name", "Id", filters=[("IsConverted", "EqualTo", False), ("Status", "NotEqualTo", "Closed - Not Converted")],
                 sort="CreatedDate", order="Desc", limit=100)
    f.screen("Scr_Select_Lead", [f.f_text("Intro_Text", "<p><b>BANT qualification</b></p>"),
                                 f.f_choice("Lead_Picker", "Lead", ["LeadChoices"])], "Get_Lead", allow_back=False)
    f.get("Get_Lead", "Lead", [("Id", "EqualTo", R("Lead_Picker"))], "Scr_BANT", "Sub_Log_Fault", first=True)
    f.screen("Scr_BANT", [
        f.f_text("Bant_Intro", "<p>{!Get_Lead.FirstName} {!Get_Lead.LastName}, {!Get_Lead.Company}</p>"),
        f.f_choice("Budget_Answer", "Budget", ["chBudgetApproved", "chBudgetPlanned", "chBudgetNone"], "RadioButtons"),
        f.f_input("Expected_Budget", "Expected budget", "Currency", scale=2),
        f.f_choice("Authority_Answer", "Authority", ["chAuthDecider", "chAuthInfluencer", "chAuthUser"], "RadioButtons"),
        f.f_choice("Need_Answer", "Need", ["chNeedCritical", "chNeedNice", "chNeedNone"]),
        f.f_choice("Timeline_Answer", "Timeline", ["chTime3", "chTime6", "chTimeLater"]),
        f.f_input("Decision_Date", "Expected decision date", "Date"),
        f.f_area("Bant_Notes", "Notes"),
        f.f_input("Apply_To_Company", "Apply rating to other open leads of this company", "Boolean", default=False)], "Dec_Score_Band")
    f.decision("Dec_Score_Band", [("Hot", [("fxBantScore", "GreaterThanOrEqualTo", 70)], "Asg_Hot"),
                                  ("Warm", [("fxBantScore", "GreaterThanOrEqualTo", 40)], "Asg_Warm")], "Asg_Cold", "Cold")
    f.assign("Asg_Hot", [("varRating", "Assign", "Hot"), ("varStatus", "Assign", "Working - Contacted")], "Update_Lead")
    f.assign("Asg_Warm", [("varRating", "Assign", "Warm"), ("varStatus", "Assign", "Working - Contacted")], "Update_Lead")
    f.assign("Asg_Cold", [("varRating", "Assign", "Cold"), ("varStatus", "Assign", "Open - Not Contacted")], "Update_Lead")
    f.update("Update_Lead", "Lead", [("Id", "EqualTo", R("Lead_Picker"))],
             {"Rating": R("varRating"), "Status": R("varStatus"), "Description": R("ttBant")}, "Dec_Apply_Siblings", "Sub_Log_Fault")
    f.decision("Dec_Apply_Siblings", [("Apply_Siblings", [("Apply_To_Company", "EqualTo", True), ("Get_Lead.Company", "IsNull", False)],
                                       "Get_Sibling_Leads")], "Dec_Hot_Task", "Only This Lead")
    f.get("Get_Sibling_Leads", "Lead", [("Company", "EqualTo", R("Get_Lead.Company")), ("IsConverted", "EqualTo", False),
                                        ("Id", "NotEqualTo", R("Lead_Picker"))], "Loop_Siblings", "Sub_Log_Fault")
    f.loop("Loop_Siblings", "Get_Sibling_Leads", "Asg_Sibling", "Update_Siblings", var="varSibling")
    f.assign("Asg_Sibling", [("varSibling.Rating", "Assign", R("varRating")), ("colSiblings", "Add", R("varSibling")), ("varSiblingCount", "Add", 1)],
             "Loop_Siblings")
    f.update("Update_Siblings", input_ref="colSiblings", nxt="Dec_Hot_Task", fault="Sub_Log_Fault")
    f.decision("Dec_Hot_Task", [("Hot_Lead", [("varRating", "EqualTo", "Hot")], "Create_Call_Task")], "Scr_Result", "No Task")
    f.create("Create_Call_Task", "Task", {"Subject": PFX + "Call hot lead", "WhoId": R("Lead_Picker"), "OwnerId": R("$User.Id"),
                                          "ActivityDate": R("fxCallDate"), "Description": R("ttBant"), "Priority": "High", "Status": "Not Started"},
             "Scr_Result", "Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p>BANT score <b>{!fxBantScore}</b> - rating <b>{!varRating}</b>, status {!varStatus}.</p>"
                                                    "<p>{!varSiblingCount} related lead(s) updated.</p>")], allow_back=False)
    error_screen(f, R("Lead_Picker"))
    f.start("Scr_Select_Lead")
    return f


def contact_roles():
    f = Flow("SCR_Opportunity_Contact_Role_Assignment", "SCR Opportunity Contact Role Assignment", "screen",
             "Pick an open Opportunity, review its current contact roles, then add or update a role (OpportunityContactRole) for a "
             "Contact of the account, show the contact's engagement and optionally create a kickoff Task.")
    f.var("varRole", "SObject", obj="OpportunityContactRole")
    f.var("varRoleCount", "Number", scale=0, default=0)
    f.var("varPrimaryExists", "Boolean", default=False)
    f.var("varEngagement", "String")
    f.var("varOpenTasks", "Number", scale=0)
    f.formula("fxKickoffDefault", "Date", "TODAY() + 3")
    f.tt("ttKickoff", "Kickoff with the new contact role ({!Role_Choice}) for opportunity {!Get_Opportunity.Name}.")
    f.record_set("OpportunityChoices", "Opportunity", "Name", "Id", filters=[("IsClosed", "EqualTo", False)], sort="CloseDate", limit=100)
    f.record_set("ContactChoices", "Contact", "Name", "Id", filters=[("AccountId", "EqualTo", R("Get_Opportunity.AccountId"))], sort="LastName")
    f.picklist_set("RoleChoices", "OpportunityContactRole", "Role")
    f.screen("Scr_Select_Opportunity", [f.f_choice("Opportunity_Picker", "Open opportunity", ["OpportunityChoices"])], "Get_Opportunity",
             allow_back=False)
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("Opportunity_Picker"))], "Get_Existing_Roles", "Sub_Log_Fault", first=True)
    f.get("Get_Existing_Roles", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("Opportunity_Picker"))], "Asg_Role_Count", "Sub_Log_Fault")
    f.assign("Asg_Role_Count", [("varRoleCount", "AssignCount", R("Get_Existing_Roles"))], "Loop_Roles")
    f.loop("Loop_Roles", "Get_Existing_Roles", "Dec_Is_Primary", "Scr_Assign_Role", var="varRole")
    f.decision("Dec_Is_Primary", [("Primary", [("varRole.IsPrimary", "EqualTo", True)], "Asg_Primary_Found")], "Loop_Roles", "Not Primary")
    f.assign("Asg_Primary_Found", [("varPrimaryExists", "Assign", True)], "Loop_Roles")
    f.screen("Scr_Assign_Role", [
        f.f_text("Roles_Text", "<p><b>{!Get_Opportunity.Name}</b> has {!varRoleCount} contact role(s). Primary contact set: {!varPrimaryExists}</p>"),
        f.f_choice("Contact_Picker", "Contact", ["ContactChoices"]),
        f.f_choice("Role_Choice", "Role", ["RoleChoices"]),
        f.f_input("Make_Primary", "Primary contact", "Boolean", default=False),
        f.f_input("Plan_Kickoff", "Create a kickoff task", "Boolean", default=True),
        f.f_input("Kickoff_Date", "Kickoff date", "Date", default=R("fxKickoffDefault"))], "Get_Contact_Role")
    f.get("Get_Contact_Role", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("Opportunity_Picker")), ("ContactId", "EqualTo", R("Contact_Picker"))],
          "Dec_Role_Exists", "Sub_Log_Fault", first=True)
    f.decision("Dec_Role_Exists", [("Role_Exists", [("Get_Contact_Role", "IsNull", False)], "Update_Role")], "Create_Role", "New Role")
    f.update("Update_Role", "OpportunityContactRole", [("Id", "EqualTo", R("Get_Contact_Role.Id"))],
             {"Role": R("Role_Choice"), "IsPrimary": R("Make_Primary")}, "Sub_Contact_Snapshot", "Sub_Log_Fault")
    f.create("Create_Role", "OpportunityContactRole", {"OpportunityId": R("Opportunity_Picker"), "ContactId": R("Contact_Picker"),
                                                       "Role": R("Role_Choice"), "IsPrimary": R("Make_Primary")}, "Sub_Contact_Snapshot", "Sub_Log_Fault")
    f.subflow("Sub_Contact_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("Contact_Picker")},
              {"outEngagement": "varEngagement", "outOpenTasks": "varOpenTasks"}, "Dec_Kickoff")
    f.decision("Dec_Kickoff", [("Kickoff_Requested", [("Plan_Kickoff", "EqualTo", True)], "Create_Kickoff_Task")], "Scr_Done", "No Kickoff")
    f.create("Create_Kickoff_Task", "Task", {"Subject": PFX + "Opportunity kickoff with contact", "WhatId": R("Opportunity_Picker"),
                                             "WhoId": R("Contact_Picker"), "OwnerId": R("Get_Opportunity.OwnerId"), "ActivityDate": R("Kickoff_Date"),
                                             "Description": R("ttKickoff"), "Priority": "Normal", "Status": "Not Started"}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Contact role saved.</b> Contact engagement: {!varEngagement} ({!varOpenTasks} open task(s)).</p>")],
             allow_back=False)
    error_screen(f, R("Opportunity_Picker"))
    f.start("Scr_Select_Opportunity")
    return f


def health_check():
    f = Flow("SCR_Account_Health_Check_Console", "SCR Account Health Check Console", "screen",
             "Pick an Account: shows the health score (subflow), pipeline summary (subflow) and open/high-priority case counts, then "
             "lets the user create an action-plan Task (replacing earlier open plans), e-mail the account owner, or do nothing.")
    f.var("varCase", "SObject", obj="Case")
    f.var("varScore", "Number", scale=0)
    f.var("varRating", "String")
    f.var("varPipeline", "Currency", scale=2)
    f.var("varWeighted", "Currency", scale=2)
    f.var("varDeals", "Number", scale=0)
    f.var("varOpenCases", "Number", scale=0, default=0)
    f.var("varHighCases", "Number", scale=0, default=0)
    f.const("cPlanSubject", "String", PFX + "Account health action plan")
    f.formula("fxDueDefault", "Date", "TODAY() + 7")
    f.formula("fxTaskPriority", "String", "IF({!varRating} = 'Cold' || {!varHighCases} > 0, 'High', 'Normal')")
    f.formula("fxEmailSubject", "String", "'Account health alert: ' & {!Get_Account.Name} & ' (' & {!varRating} & ')'")
    f.tt("ttSummary", "Health score {!varScore} ({!varRating}). Pipeline {!varPipeline} (weighted {!varWeighted}) in {!varDeals} deal(s). "
                      "Open cases: {!varOpenCases}, high priority: {!varHighCases}.\nNotes: {!Action_Notes}")
    f.tt("ttEmail", "Hello {!Get_Owner.FirstName},\n\n{!$User.FirstName} {!$User.LastName} reviewed account {!Get_Account.Name}.\n{!ttSummary}\n\n"
                    "Please follow up by {!Action_Due}.")
    f.choice("chPlan", "Create an action plan task", "Plan")
    f.choice("chEscalate", "Email the account owner", "Escalate")
    f.choice("chNone", "No action", "None")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Get_Account", allow_back=False)
    f.get("Get_Account", "Account", [("Id", "EqualTo", R("Account_Picker"))], "Sub_Health_Score", "Sub_Log_Fault", first=True)
    f.subflow("Sub_Health_Score", "AUT_Account_Health_Calculator", {"inAccountId": R("Account_Picker")},
              {"outScore": "varScore", "outRating": "varRating"}, "Sub_Pipeline")
    f.subflow("Sub_Pipeline", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("Account_Picker"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline", "outWeightedPipeline": "varWeighted", "outDealCount": "varDeals"}, "Get_Open_Cases")
    f.get("Get_Open_Cases", "Case", [("AccountId", "EqualTo", R("Account_Picker")), ("IsClosed", "EqualTo", False)], "Asg_Case_Count", "Sub_Log_Fault")
    f.assign("Asg_Case_Count", [("varOpenCases", "AssignCount", R("Get_Open_Cases"))], "Loop_Cases")
    f.loop("Loop_Cases", "Get_Open_Cases", "Dec_High_Priority", "Scr_Health_Results", var="varCase")
    f.decision("Dec_High_Priority", [("High_Priority", [("varCase.Priority", "EqualTo", "High")], "Asg_High_Case")], "Loop_Cases", "Other")
    f.assign("Asg_High_Case", [("varHighCases", "Add", 1)], "Loop_Cases")
    f.screen("Scr_Health_Results", [
        f.f_text("Results_Text", "<p><b>{!Get_Account.Name}</b></p><p>Health score: <b>{!varScore}</b> ({!varRating})</p>"
                                 "<p>Pipeline: {!varPipeline} (weighted {!varWeighted}) in {!varDeals} deal(s)</p>"
                                 "<p>Open cases: {!varOpenCases}, high priority: {!varHighCases}</p>"),
        f.f_choice("Next_Action", "Next step", ["chPlan", "chEscalate", "chNone"], "RadioButtons", default_choice="chNone"),
        f.f_input("Action_Due", "Follow-up due", "Date", default=R("fxDueDefault")),
        f.f_area("Action_Notes", "Notes")], "Dec_Next_Action", allow_back=False)
    f.decision("Dec_Next_Action", [("Plan", [("Next_Action", "EqualTo", "Plan")], "Delete_Old_Plans"),
                                   ("Escalate", [("Next_Action", "EqualTo", "Escalate")], "Get_Owner")], "Scr_Done", "No Action")
    f.delete("Delete_Old_Plans", "Task", [("WhatId", "EqualTo", R("Account_Picker")), ("Subject", "EqualTo", R("cPlanSubject")),
                                          ("IsClosed", "EqualTo", False)], "Create_Action_Plan", "Sub_Log_Fault")
    f.create("Create_Action_Plan", "Task", {"Subject": R("cPlanSubject"), "WhatId": R("Account_Picker"), "OwnerId": R("Get_Account.OwnerId"),
                                            "ActivityDate": R("Action_Due"), "Description": R("ttSummary"), "Priority": R("fxTaskPriority"),
                                            "Status": "Not Started"}, "Scr_Done", "Sub_Log_Fault")
    f.get("Get_Owner", "User", [("Id", "EqualTo", R("Get_Account.OwnerId"))], "Email_Owner", "Sub_Log_Fault", first=True)
    f.email("Email_Owner", R("Get_Owner.Email"), R("fxEmailSubject"), R("ttEmail"), "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p>Health check finished for {!Get_Account.Name}.</p>")], allow_back=False)
    error_screen(f, R("Account_Picker"))
    f.start("Scr_Select_Account")
    return f


def task_reassign_console():
    f = Flow("SCR_Task_Bulk_Reassign_Console", "SCR Task Bulk Reassign Console", "screen",
             "UI for AUT_Task_Bulk_Reassign: pick source and target users, preview open/overdue/high-priority task counts, confirm, "
             "run the reassignment subflow, e-mail the new owner and log an audit Task.")
    f.var("varTask", "SObject", obj="Task")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varOverdue", "Number", scale=0, default=0)
    f.var("varHigh", "Number", scale=0, default=0)
    f.var("varMoved", "Number", scale=0, default=0)
    f.var("varResult", "String")
    f.formula("fxIsOverdue", "Number", "IF(AND(NOT(ISBLANK({!varTask.ActivityDate})), {!varTask.ActivityDate} < TODAY()), 1, 0)", scale=0)
    f.formula("fxIsHigh", "Number", "IF(TEXT({!varTask.Priority}) = 'High', 1, 0)", scale=0)
    f.formula("fxEmailSubject", "String", "TEXT({!varMoved}) & ' task(s) were reassigned to you'")
    f.tt("ttEmail", "Hello {!Get_To_User.FirstName},\n\n{!varMoved} open task(s) were moved to you by {!$User.FirstName} {!$User.LastName}.\n"
                    "Reason: {!Reassign_Reason}\n{!Reassign_Notes}")
    f.tt("ttAudit", "Reassignment from {!From_User} to {!To_User} (high only: {!High_Only}). Reason: {!Reassign_Reason}. Result: {!varResult}")
    f.choice("chVacation", "Vacation / leave", "Vacation")
    f.choice("chRoleChange", "Role change", "Role change")
    f.choice("chWorkload", "Workload balancing", "Workload")
    f.choice("chConfirm", "Reassign now", "Confirm")
    f.choice("chAbort", "Cancel", "Abort")
    f.record_set("FromUserChoices", "User", "Name", "Id", filters=[("IsActive", "EqualTo", True)], sort="Name")
    f.record_set("ToUserChoices", "User", "Name", "Id", filters=[("IsActive", "EqualTo", True)], sort="Name")
    f.screen("Scr_Select_Users", [
        f.f_text("Intro_Text", "<p><b>Bulk task reassignment</b></p>"),
        f.f_choice("From_User", "From user", ["FromUserChoices"]),
        f.f_choice("To_User", "To user", ["ToUserChoices"]),
        f.f_input("High_Only", "Only High priority tasks", "Boolean", default=False),
        f.f_choice("Reassign_Reason", "Reason", ["chVacation", "chRoleChange", "chWorkload"], default_choice="chWorkload"),
        f.f_area("Reassign_Notes", "Notes for the new owner")], "Dec_Same_User", allow_back=False)
    f.decision("Dec_Same_User", [("Same_User", [("From_User", "EqualTo", R("To_User"))], "Scr_Same_User")], "Get_Open_Tasks", "Different")
    f.screen("Scr_Same_User", [f.f_text("Same_User_Text", "<p>Source and target user must be different. Go back and fix it.</p>")])
    f.get("Get_Open_Tasks", "Task", [("OwnerId", "EqualTo", R("From_User")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Sub_Log_Fault")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Tasks"))], "Loop_Tasks")
    f.loop("Loop_Tasks", "Get_Open_Tasks", "Asg_Tally", "Scr_Preview", var="varTask")
    f.assign("Asg_Tally", [("varOverdue", "Add", R("fxIsOverdue")), ("varHigh", "Add", R("fxIsHigh"))], "Loop_Tasks")
    f.screen("Scr_Preview", [
        f.f_text("Preview_Text", "<p>The source user has <b>{!varOpenCount}</b> open task(s): {!varOverdue} overdue, {!varHigh} high priority.</p>"
                                 "<p>High priority only: {!High_Only}</p>"),
        f.f_choice("Confirm_Action", "Proceed?", ["chConfirm", "chAbort"], "RadioButtons", default_choice="chAbort")], "Dec_Confirm")
    f.decision("Dec_Confirm", [("Confirmed", [("Confirm_Action", "EqualTo", "Confirm"), ("varOpenCount", "GreaterThan", 0)], "Sub_Reassign")],
               "Scr_Cancelled", "Cancel")
    f.subflow("Sub_Reassign", "AUT_Task_Bulk_Reassign", {"inFromUserId": R("From_User"), "inToUserId": R("To_User"), "inHighOnly": R("High_Only")},
              {"outMovedCount": "varMoved", "outResult": "varResult"}, "Dec_Moved")
    f.decision("Dec_Moved", [("Moved", [("varMoved", "GreaterThan", 0)], "Get_To_User")], "Scr_Result", "Nothing Moved")
    f.get("Get_To_User", "User", [("Id", "EqualTo", R("To_User"))], "Email_New_Owner", "Sub_Log_Fault", first=True)
    f.email("Email_New_Owner", R("Get_To_User.Email"), R("fxEmailSubject"), R("ttEmail"), "Create_Audit_Task", "Sub_Log_Fault")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Bulk task reassignment", "Description": R("ttAudit"), "OwnerId": R("$User.Id"),
                                           "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, "Scr_Result", "Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p><b>{!varMoved}</b> task(s) moved. {!varResult}</p>")], allow_back=False)
    f.screen("Scr_Cancelled", [f.f_text("Cancelled_Text", "<p>No tasks were reassigned.</p>")], allow_back=False)
    error_screen(f, R("From_User"))
    f.start("Scr_Select_Users")
    return f


def opportunity_clone():
    f = Flow("SCR_Opportunity_Clone_Lite", "SCR Opportunity Clone Lite", "screen",
             "Clone an Opportunity with a new name/stage/close date/amount and optionally copy its product lines and contact roles "
             "(bulk creates), then show the account's refreshed pipeline.")
    f.var("varNewOppId", "String")
    f.var("varLine", "SObject", obj="OpportunityLineItem")
    f.var("varNewLine", "SObject", obj="OpportunityLineItem")
    f.var("colNewLines", "SObject", coll=True, obj="OpportunityLineItem")
    f.var("varRole", "SObject", obj="OpportunityContactRole")
    f.var("varNewRole", "SObject", obj="OpportunityContactRole")
    f.var("colNewRoles", "SObject", coll=True, obj="OpportunityContactRole")
    f.var("varLineCount", "Number", scale=0, default=0)
    f.var("varRoleCount", "Number", scale=0, default=0)
    f.var("varPipeline", "Currency", scale=2)
    f.formula("fxDefaultName", "String", f"LEFT('{PFX}' & {{!Get_Opportunity.Name}} & ' (Copy)', 120)")
    f.formula("fxCloneName", "String", f"IF(BEGINS({{!New_Name}}, '{PFX}'), {{!New_Name}}, LEFT('{PFX}' & {{!New_Name}}, 120))")
    f.formula("fxDefaultClose", "Date", "TODAY() + 90")
    f.record_set("OpportunityChoices", "Opportunity", "Name", "Id", sort="CreatedDate", order="Desc", limit=100)
    f.picklist_set("StageChoices", "Opportunity", "StageName")
    f.screen("Scr_Select_Opportunity", [f.f_choice("Opportunity_Picker", "Opportunity to clone", ["OpportunityChoices"])], "Get_Opportunity",
             allow_back=False)
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("Opportunity_Picker"))], "Scr_Clone_Options", "Sub_Log_Fault", first=True)
    f.screen("Scr_Clone_Options", [
        f.f_text("Clone_Intro", "<p>Cloning <b>{!Get_Opportunity.Name}</b></p>"),
        f.f_input("New_Name", "New name", "String", required=True, default=R("fxDefaultName")),
        f.f_choice("New_Stage", "Stage", ["StageChoices"]),
        f.f_input("New_Close_Date", "Close date", "Date", required=True, default=R("fxDefaultClose")),
        f.f_input("New_Amount", "Amount", "Currency", scale=2, default=R("Get_Opportunity.Amount")),
        f.f_input("Copy_Related", "Copy product lines and contact roles", "Boolean", default=True)], "Create_Clone")
    f.create("Create_Clone", "Opportunity", {"Name": R("fxCloneName"), "AccountId": R("Get_Opportunity.AccountId"), "StageName": R("New_Stage"),
                                             "CloseDate": R("New_Close_Date"), "Amount": R("New_Amount"), "Type": R("Get_Opportunity.Type"),
                                             "LeadSource": R("Get_Opportunity.LeadSource"), "Description": R("Get_Opportunity.Description"),
                                             "Pricebook2Id": R("Get_Opportunity.Pricebook2Id")}, "Dec_Copy_Related", "Sub_Log_Fault", id_to="varNewOppId")
    f.decision("Dec_Copy_Related", [("Copy", [("Copy_Related", "EqualTo", True)], "Get_Lines")], "Sub_Pipeline", "No Copy")
    f.get("Get_Lines", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("Opportunity_Picker"))], "Loop_Lines", "Sub_Log_Fault")
    f.loop("Loop_Lines", "Get_Lines", "Asg_New_Line", "Dec_Any_Lines", var="varLine")
    f.assign("Asg_New_Line", [("varNewLine.OpportunityId", "Assign", R("varNewOppId")), ("varNewLine.PricebookEntryId", "Assign", R("varLine.PricebookEntryId")),
                              ("varNewLine.Quantity", "Assign", R("varLine.Quantity")), ("varNewLine.UnitPrice", "Assign", R("varLine.UnitPrice")),
                              ("varNewLine.Description", "Assign", R("varLine.Description")), ("colNewLines", "Add", R("varNewLine")),
                              ("varLineCount", "Add", 1)], "Loop_Lines")
    f.decision("Dec_Any_Lines", [("Has_Lines", [("varLineCount", "GreaterThan", 0)], "Create_Lines")], "Get_Roles", "No Lines")
    f.create("Create_Lines", input_ref="colNewLines", nxt="Get_Roles", fault="Sub_Log_Fault")
    f.get("Get_Roles", "OpportunityContactRole", [("OpportunityId", "EqualTo", R("Opportunity_Picker"))], "Loop_Roles", "Sub_Log_Fault")
    f.loop("Loop_Roles", "Get_Roles", "Asg_New_Role", "Dec_Any_Roles", var="varRole")
    f.assign("Asg_New_Role", [("varNewRole.OpportunityId", "Assign", R("varNewOppId")), ("varNewRole.ContactId", "Assign", R("varRole.ContactId")),
                              ("varNewRole.Role", "Assign", R("varRole.Role")), ("varNewRole.IsPrimary", "Assign", R("varRole.IsPrimary")),
                              ("colNewRoles", "Add", R("varNewRole")), ("varRoleCount", "Add", 1)], "Loop_Roles")
    f.decision("Dec_Any_Roles", [("Has_Roles", [("varRoleCount", "GreaterThan", 0)], "Create_Roles")], "Sub_Pipeline", "No Roles")
    f.create("Create_Roles", input_ref="colNewRoles", nxt="Sub_Pipeline", fault="Sub_Log_Fault")
    f.subflow("Sub_Pipeline", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("Get_Opportunity.AccountId"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline"}, "Scr_Done")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Clone created</b> (Id {!varNewOppId}) with {!varLineCount} product line(s) and "
                                                "{!varRoleCount} contact role(s).</p><p>Account pipeline is now {!varPipeline}.</p>")], allow_back=False)
    error_screen(f, R("varNewOppId"))
    f.start("Scr_Select_Opportunity")
    return f


def case_duplicate_review():
    f = Flow("SCR_Case_Duplicate_Review", "SCR Case Duplicate Review", "screen",
             "Pick an open Case, find likely duplicates on the same Account (same contact or same subject) with a collection filter, "
             "then close one as duplicate or link it as a child case (no real merge) and log a review Task.")
    f.var("varDup", "SObject", obj="Case")
    f.var("varLikelyCount", "Number", scale=0, default=0)
    f.var("varDupList", "String", default="")
    f.formula("fxDupLine", "String", "{!varDup.CaseNumber} & ' - ' & BLANKVALUE({!varDup.Subject}, '(no subject)') & ' [' & TEXT({!varDup.Status}) & ']; '")
    f.tt("ttReview", "Duplicate review of case {!Get_Case.CaseNumber}: action {!Review_Action} on case {!Duplicate_Picker}. "
                     "Likely duplicates: {!varDupList}\nComment: {!Review_Comment}")
    f.choice("chClose", "Close the other case as duplicate", "Close")
    f.choice("chLink", "Link it as a child case", "Link")
    f.choice("chKeep", "Not a duplicate - keep both", "Keep")
    f.record_set("CaseChoices", "Case", "CaseNumber", "Id", filters=[("IsClosed", "EqualTo", False)], sort="CreatedDate", order="Desc", limit=200)
    f.record_set("DuplicateChoices", "Case", "CaseNumber", "Id", filters=[("AccountId", "EqualTo", R("Get_Case.AccountId")), ("IsClosed", "EqualTo", False),
                                                                          ("Id", "NotEqualTo", R("Case_Picker"))], sort="CreatedDate")
    f.screen("Scr_Select_Case", [f.f_text("Intro_Text", "<p><b>Duplicate case review</b></p>"),
                                 f.f_choice("Case_Picker", "Case to keep (master)", ["CaseChoices"])], "Get_Case", allow_back=False)
    f.get("Get_Case", "Case", [("Id", "EqualTo", R("Case_Picker"))], "Dec_Has_Account", "Sub_Log_Fault", first=True)
    f.decision("Dec_Has_Account", [("Has_Account", [("Get_Case.AccountId", "IsNull", False)], "Get_Candidates")], "Scr_No_Duplicates", "No Account")
    f.get("Get_Candidates", "Case", [("AccountId", "EqualTo", R("Get_Case.AccountId")), ("IsClosed", "EqualTo", False),
                                     ("Id", "NotEqualTo", R("Case_Picker"))], "Filter_Likely", "Sub_Log_Fault", sort="CreatedDate")
    f.filter_coll("Filter_Likely", "Get_Candidates", "Case", [("ContactId", "IsNull", False), ("ContactId", "EqualTo", R("Get_Case.ContactId")),
                                                              ("Subject", "EqualTo", R("Get_Case.Subject"))], "Asg_Likely_Count",
                  logic="(1 AND 2) OR 3")
    f.assign("Asg_Likely_Count", [("varLikelyCount", "AssignCount", R("Filter_Likely"))], "Dec_Any_Likely")
    f.decision("Dec_Any_Likely", [("Has_Likely", [("varLikelyCount", "GreaterThan", 0)], "Loop_Likely")], "Scr_No_Duplicates", "None")
    f.loop("Loop_Likely", "Filter_Likely", "Asg_Dup_Line", "Scr_Review", var="varDup")
    f.assign("Asg_Dup_Line", [("varDupList", "Add", R("fxDupLine"))], "Loop_Likely")
    f.screen("Scr_Review", [
        f.f_text("Review_Text", "<p>Master case <b>{!Get_Case.CaseNumber}</b>: {!Get_Case.Subject}</p>"
                                "<p>{!varLikelyCount} likely duplicate(s): {!varDupList}</p>"),
        f.f_choice("Duplicate_Picker", "Case to review", ["DuplicateChoices"]),
        f.f_choice("Review_Action", "Decision", ["chClose", "chLink", "chKeep"], "RadioButtons", default_choice="chLink"),
        f.f_area("Review_Comment", "Comment")], "Dec_Review_Action")
    f.decision("Dec_Review_Action", [("Close_Duplicate", [("Review_Action", "EqualTo", "Close")], "Update_Close_Duplicate"),
                                     ("Link_Duplicate", [("Review_Action", "EqualTo", "Link")], "Update_Link_Duplicate")],
               "Create_Review_Task", "Keep Both")
    f.update("Update_Close_Duplicate", "Case", [("Id", "EqualTo", R("Duplicate_Picker"))], {"Status": "Closed", "ParentId": R("Case_Picker")},
             "Create_Review_Task", "Sub_Log_Fault")
    f.update("Update_Link_Duplicate", "Case", [("Id", "EqualTo", R("Duplicate_Picker"))], {"ParentId": R("Case_Picker")},
             "Create_Review_Task", "Sub_Log_Fault")
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Duplicate case review", "WhatId": R("Case_Picker"), "Description": R("ttReview"),
                                            "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p>Review saved ({!Review_Action}).</p>")], allow_back=False)
    f.screen("Scr_No_Duplicates", [f.f_text("No_Duplicates_Text", "<p>No likely duplicates found for this case.</p>")])
    error_screen(f, R("Case_Picker"))
    f.start("Scr_Select_Case")
    return f


def product_adder():
    f = Flow("SCR_Opportunity_Product_Adder", "SCR Opportunity Product Adder", "screen",
             "Pick an open Opportunity and a Product2; resolves the price book (opportunity's or the standard one) and its "
             "PricebookEntry, then increases the quantity of an existing line or creates a new OpportunityLineItem.")
    f.var("varLine", "SObject", obj="OpportunityLineItem")
    f.var("varPricebookId", "String")
    f.var("varLineId", "String")
    f.var("varExistingQty", "Number", scale=2, default=0)
    f.formula("fxNewQty", "Number", "{!varExistingQty} + {!Line_Quantity}", scale=2)
    f.formula("fxUnitPrice", "Currency", "IF(OR(ISBLANK({!Unit_Price}), {!Unit_Price} <= 0), {!Get_Pricebook_Entry.UnitPrice}, {!Unit_Price})", scale=2)
    f.record_set("OpportunityChoices", "Opportunity", "Name", "Id", filters=[("IsClosed", "EqualTo", False)], sort="CloseDate", limit=100)
    f.record_set("ProductChoices", "Product2", "Name", "Id", filters=[("IsActive", "EqualTo", True)], sort="Name")
    f.screen("Scr_Select_Opportunity", [f.f_choice("Opportunity_Picker", "Open opportunity", ["OpportunityChoices"])], "Get_Opportunity",
             allow_back=False)
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("Opportunity_Picker"))], "Dec_Has_Pricebook", "Sub_Log_Fault", first=True)
    f.decision("Dec_Has_Pricebook", [("Has_Pricebook", [("Get_Opportunity.Pricebook2Id", "IsNull", False)], "Asg_Opp_Pricebook")],
               "Get_Std_Pricebook", "No Pricebook")
    f.assign("Asg_Opp_Pricebook", [("varPricebookId", "Assign", R("Get_Opportunity.Pricebook2Id"))], "Scr_Select_Product")
    f.get("Get_Std_Pricebook", "Pricebook2", [("IsStandard", "EqualTo", True)], "Dec_Std_Found", "Sub_Log_Fault", first=True)
    f.decision("Dec_Std_Found", [("Std_Found", [("Get_Std_Pricebook", "IsNull", False)], "Asg_Std_Pricebook")], "Scr_Not_Priced", "Missing")
    f.assign("Asg_Std_Pricebook", [("varPricebookId", "Assign", R("Get_Std_Pricebook.Id"))], "Scr_Select_Product")
    f.screen("Scr_Select_Product", [
        f.f_text("Product_Intro", "<p>Add a product to <b>{!Get_Opportunity.Name}</b></p>"),
        f.f_choice("Product_Picker", "Product", ["ProductChoices"]),
        f.f_input("Line_Quantity", "Quantity", "Number", required=True, scale=2, default=1),
        f.f_input("Unit_Price", "Sales price (blank = list price)", "Currency", scale=2),
        f.f_input("Service_Date", "Service date", "Date"),
        f.f_input("Line_Description", "Line description", "String")], "Get_Pricebook_Entry")
    f.get("Get_Pricebook_Entry", "PricebookEntry", [("Pricebook2Id", "EqualTo", R("varPricebookId")), ("Product2Id", "EqualTo", R("Product_Picker")),
                                                    ("IsActive", "EqualTo", True)], "Dec_Entry_Found", "Sub_Log_Fault", first=True)
    f.decision("Dec_Entry_Found", [("Entry_Found", [("Get_Pricebook_Entry", "IsNull", False)], "Get_Existing_Lines")], "Scr_Not_Priced", "Not Priced")
    f.get("Get_Existing_Lines", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("Opportunity_Picker")),
                                                        ("PricebookEntryId", "EqualTo", R("Get_Pricebook_Entry.Id"))], "Loop_Lines", "Sub_Log_Fault",
          sort="CreatedDate")
    f.loop("Loop_Lines", "Get_Existing_Lines", "Asg_Existing_Line", "Dec_Line_Exists", var="varLine")
    f.assign("Asg_Existing_Line", [("varLineId", "Assign", R("varLine.Id")), ("varExistingQty", "Assign", R("varLine.Quantity"))], "Loop_Lines")
    f.decision("Dec_Line_Exists", [("Line_Exists", [("varLineId", "IsNull", False)], "Update_Line")], "Create_Line", "New Line")
    f.update("Update_Line", "OpportunityLineItem", [("Id", "EqualTo", R("varLineId"))], {"Quantity": R("fxNewQty")}, "Scr_Done", "Sub_Log_Fault")
    f.create("Create_Line", "OpportunityLineItem", {"OpportunityId": R("Opportunity_Picker"), "PricebookEntryId": R("Get_Pricebook_Entry.Id"),
                                                    "Quantity": R("Line_Quantity"), "UnitPrice": R("fxUnitPrice"), "ServiceDate": R("Service_Date"),
                                                    "Description": R("Line_Description")}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Product saved</b> on {!Get_Opportunity.Name}.</p>")], allow_back=False)
    f.screen("Scr_Not_Priced", [f.f_text("Not_Priced_Text", "<p>No active price book entry exists for this product (or no standard price book). "
                                                            "Go back and pick another product.</p>")])
    error_screen(f, R("Opportunity_Picker"))
    f.start("Scr_Select_Opportunity")
    return f


ALL = [asset_registration, contract_wizard, event_rescheduler, bant_survey, contact_roles, health_check, task_reassign_console,
       opportunity_clone, case_duplicate_review, product_adder]

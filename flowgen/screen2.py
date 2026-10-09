from flowlib import Flow, R, D
from common import log_fault, PFX
from screen import error_screen


def contact_update():
    f = Flow("SCR_Contact_Quick_Update", "SCR Contact Quick Update", "screen",
             "Pick an Account, then one of its Contacts; edit title/e-mail/phone (prefilled), show an activity snapshot from subflow, "
             "update the Contact and log a completed Task when the e-mail changed.")
    f.var("varEngagement", "String")
    f.var("varOverdue", "Number", scale=0)
    f.tt("ttChange", "Email changed from {!Get_Contact.Email} to {!New_Email} by {!$User.Username}.")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.record_set("ContactChoices", "Contact", "Name", "Id", filters=[("AccountId", "EqualTo", R("Account_Picker"))], sort="LastName")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Scr_Select_Contact", allow_back=False)
    f.screen("Scr_Select_Contact", [f.f_choice("Contact_Picker", "Contact", ["ContactChoices"])], "Get_Contact")
    f.get("Get_Contact", "Contact", [("Id", "EqualTo", R("Contact_Picker"))], "Dec_Contact_Found", "Sub_Log_Fault", first=True)
    f.decision("Dec_Contact_Found", [("Found", [("Get_Contact", "IsNull", False)], "Sub_Activity_Snapshot")], "Scr_Not_Found", "Not Found")
    f.subflow("Sub_Activity_Snapshot", "AUT_Contact_Activity_Snapshot", {"inContactId": R("Contact_Picker")},
              {"outEngagement": "varEngagement", "outOverdueTasks": "varOverdue"}, "Scr_Edit_Contact")
    f.screen("Scr_Edit_Contact", [
        f.f_text("Snapshot_Text", "<p><b>{!Get_Contact.Name}</b> — engagement: {!varEngagement}, overdue tasks: {!varOverdue}</p>"),
        f.f_input("New_Title", "Title", "String", default=R("Get_Contact.Title")),
        f.f_input("New_Email", "Email", "String", default=R("Get_Contact.Email")),
        f.f_input("New_Phone", "Phone", "String", default=R("Get_Contact.Phone"))], "Update_Contact", allow_back=False)
    f.update("Update_Contact", "Contact", [("Id", "EqualTo", R("Contact_Picker"))],
             {"Title": R("New_Title"), "Email": R("New_Email"), "Phone": R("New_Phone")}, "Dec_Email_Changed", "Sub_Log_Fault")
    f.decision("Dec_Email_Changed", [("Email_Changed", [("New_Email", "NotEqualTo", R("Get_Contact.Email"))], "Create_Change_Log")], "Scr_Done", "Same Email")
    f.create("Create_Change_Log", "Task", {"Subject": PFX + "Contact email changed", "WhoId": R("Contact_Picker"), "Description": R("ttChange"),
                                           "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p><b>Saved.</b> {!Get_Contact.Name} was updated.</p>")], allow_back=False)
    f.screen("Scr_Not_Found", [f.f_text("Not_Found_Text", "<p>The contact could not be loaded.</p>")])
    error_screen(f, R("Contact_Picker"))
    f.start("Scr_Select_Account")
    return f


def case_bulk_close():
    f = Flow("SCR_Case_Bulk_Close", "SCR Case Bulk Close", "screen",
             "Pick an Account, review its open Cases, choose a reason and comment, optionally only Low priority ones; closes them in "
             "one bulk update and writes an audit Task.")
    f.var("varCase", "SObject", obj="Case")
    f.var("colSource", "SObject", coll=True, obj="Case")
    f.var("colToClose", "SObject", coll=True, obj="Case")
    f.var("varOpenCount", "Number", scale=0, default=0)
    f.var("varClosed", "Number", scale=0, default=0)
    f.formula("fxComment", "String", "LEFT(BLANKVALUE({!varCase.Description}, '') & ' || ' & 'Closed in bulk: ' & BLANKVALUE({!Close_Comment}, ''), 31000)")
    f.tt("ttAudit", "{!varClosed} case(s) closed in bulk by {!$User.Username}. Reason: {!Close_Reason}. Comment: {!Close_Comment}")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.picklist_set("ReasonChoices", "Case", "Reason")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Account", ["AccountChoices"])], "Get_Open_Cases", allow_back=False)
    f.get("Get_Open_Cases", "Case", [("AccountId", "EqualTo", R("Account_Picker")), ("IsClosed", "EqualTo", False)], "Asg_Open_Count", "Sub_Log_Fault",
          sort="CreatedDate")
    f.assign("Asg_Open_Count", [("varOpenCount", "AssignCount", R("Get_Open_Cases"))], "Dec_Has_Cases")
    f.decision("Dec_Has_Cases", [("Has_Cases", [("varOpenCount", "GreaterThan", 0)], "Scr_Close_Options")], "Scr_No_Cases", "None")
    f.screen("Scr_Close_Options", [
        f.f_text("Options_Intro", "<p>{!varOpenCount} open case(s) found.</p>"),
        f.f_choice("Close_Reason", "Case reason", ["ReasonChoices"]),
        f.f_area("Close_Comment", "Closing comment", required=True),
        f.f_input("Low_Only", "Close only Low priority cases", "Boolean", default=True)], "Dec_Scope")
    f.decision("Dec_Scope", [("Low_Only_Scope", [("Low_Only", "EqualTo", True)], "Filter_Low_Priority")], "Asg_All_Cases", "All Cases")
    f.filter_coll("Filter_Low_Priority", "Get_Open_Cases", "Case", [("Priority", "EqualTo", "Low")], "Asg_Low_Cases")
    f.assign("Asg_Low_Cases", [("colSource", "Assign", R("Filter_Low_Priority"))], "Loop_Cases")
    f.assign("Asg_All_Cases", [("colSource", "Assign", R("Get_Open_Cases"))], "Loop_Cases")
    f.loop("Loop_Cases", "colSource", "Asg_Close_Case", "Dec_Anything", var="varCase")
    f.assign("Asg_Close_Case", [("varCase.Description", "Assign", R("fxComment")), ("varCase.Status", "Assign", "Closed"),
                                ("varCase.Reason", "Assign", R("Close_Reason")), ("colToClose", "Add", R("varCase")), ("varClosed", "Add", 1)], "Loop_Cases")
    f.decision("Dec_Anything", [("Has_Cases_To_Close", [("varClosed", "GreaterThan", 0)], "Update_Cases")], "Scr_Result", "Nothing")
    f.update("Update_Cases", input_ref="colToClose", nxt="Create_Audit_Task", fault="Sub_Log_Fault")
    f.create("Create_Audit_Task", "Task", {"Subject": PFX + "Bulk case closure", "WhatId": R("Account_Picker"), "Description": R("ttAudit"),
                                           "Status": "Completed", "Priority": "Low", "ActivityDate": R("$Flow.CurrentDate")}, "Scr_Result", "Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p><b>{!varClosed}</b> of {!varOpenCount} case(s) closed.</p>")], allow_back=False)
    f.screen("Scr_No_Cases", [f.f_text("No_Cases_Text", "<p>This account has no open cases.</p>")])
    error_screen(f, R("Account_Picker"))
    f.start("Scr_Select_Account")
    return f


def discount_calc():
    f = Flow("SCR_Opportunity_Discount_Calculator", "SCR Opportunity Discount Calculator", "screen",
             "Pick an open Opportunity, sum its product lines, enter a discount; discounts above 20% require a justification. Saves the "
             "proposal to NextStep/Description and creates a review Task.")
    f.var("varLineTotal", "Currency", scale=2, default=0)
    f.var("varLineCount", "Number", scale=0, default=0)
    f.var("varLine", "SObject", obj="OpportunityLineItem")
    f.formula("fxBase", "Currency", "IF({!varLineTotal} > 0, {!varLineTotal}, BLANKVALUE({!Get_Opportunity.Amount}, 0))", scale=2)
    f.formula("fxDiscounted", "Currency", "{!fxBase} * (1 - {!Discount_Percent} / 100)", scale=2)
    f.formula("fxLineTotal", "Currency", "BLANKVALUE({!varLine.TotalPrice}, 0)", scale=2)
    f.formula("fxNextStep", "String", "LEFT('Proposed ' & TEXT({!Discount_Percent}) & '% discount: ' & TEXT({!fxDiscounted}), 255)")
    f.tt("ttProposal", "Base: {!fxBase} ({!varLineCount} product line(s))\nDiscount: {!Discount_Percent}%\nProposed price: {!fxDiscounted}\n"
                       "Justification: {!Justification}\nBy: {!$User.Username}")
    f.record_set("OpportunityChoices", "Opportunity", "Name", "Id", filters=[("IsClosed", "EqualTo", False)], sort="CloseDate", limit=100)
    f.screen("Scr_Select_Opportunity", [f.f_choice("Opportunity_Picker", "Open opportunity", ["OpportunityChoices"])], "Get_Opportunity", allow_back=False)
    f.get("Get_Opportunity", "Opportunity", [("Id", "EqualTo", R("Opportunity_Picker"))], "Get_Line_Items", "Sub_Log_Fault", first=True)
    f.get("Get_Line_Items", "OpportunityLineItem", [("OpportunityId", "EqualTo", R("Opportunity_Picker"))], "Loop_Lines", "Sub_Log_Fault")
    f.loop("Loop_Lines", "Get_Line_Items", "Asg_Add_Line", "Scr_Discount", var="varLine")
    f.assign("Asg_Add_Line", [("varLineTotal", "Add", R("fxLineTotal")), ("varLineCount", "Add", 1)], "Loop_Lines")
    f.screen("Scr_Discount", [
        f.f_text("Base_Text", "<p>Base value: <b>{!fxBase}</b> from {!varLineCount} product line(s).</p>"),
        f.f_input("Discount_Percent", "Discount, %", "Number", required=True, scale=2, default=10)], "Dec_Discount_Level")
    f.decision("Dec_Discount_Level", [
        ("Invalid", [("Discount_Percent", "LessThan", 0), ("Discount_Percent", "GreaterThan", 90)], "Scr_Invalid_Discount", "or"),
        ("Needs_Justification", [("Discount_Percent", "GreaterThan", 20)], "Scr_Justification")], "Update_Opportunity", "Standard")
    f.screen("Scr_Justification", [f.f_text("Justification_Intro", "<p>Discounts above 20% need a justification.</p>"),
                                   f.f_area("Justification", "Justification", required=True)], "Update_Opportunity")
    f.update("Update_Opportunity", "Opportunity", [("Id", "EqualTo", R("Opportunity_Picker"))], {"NextStep": R("fxNextStep")},
             "Create_Review_Task", "Sub_Log_Fault")
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Review discount proposal", "WhatId": R("Opportunity_Picker"), "Description": R("ttProposal"),
                                            "OwnerId": R("Get_Opportunity.OwnerId"), "Priority": "Normal", "Status": "Not Started"},
             "Scr_Result", "Sub_Log_Fault")
    f.screen("Scr_Result", [f.f_text("Result_Text", "<p>Proposed price <b>{!fxDiscounted}</b> saved to Next Step; a review task was created.</p>")],
             allow_back=False)
    f.screen("Scr_Invalid_Discount", [f.f_text("Invalid_Text", "<p>The discount must be between 0 and 90%. Go back and correct it.</p>")])
    error_screen(f, R("Opportunity_Picker"))
    f.start("Scr_Select_Opportunity")
    return f


def hierarchy():
    f = Flow("SCR_Account_Hierarchy_Overview", "SCR Account Hierarchy Overview", "screen",
             "Pick an Account: lists its child accounts with combined annual revenue, shows the parent's pipeline from subflow and "
             "optionally creates a hierarchy review Task.")
    f.var("varChild", "SObject", obj="Account")
    f.var("varChildCount", "Number", scale=0, default=0)
    f.var("varChildRevenue", "Currency", scale=2, default=0)
    f.var("varChildList", "String", default="")
    f.var("varPipeline", "Currency", scale=2)
    f.var("varDeals", "Number", scale=0)
    f.formula("fxRevenue", "Currency", "BLANKVALUE({!varChild.AnnualRevenue}, 0)", scale=2)
    f.formula("fxChildLine", "String", "{!varChild.Name} & ' (' & BLANKVALUE(TEXT({!varChild.Type}), 'n/a') & ')'")
    f.tt("ttReview", "Hierarchy review: {!varChildCount} child account(s), combined revenue {!varChildRevenue}, parent pipeline {!varPipeline}.\n{!varChildList}")
    f.record_set("AccountChoices", "Account", "Name", "Id", sort="Name")
    f.screen("Scr_Select_Account", [f.f_choice("Account_Picker", "Parent account", ["AccountChoices"])], "Get_Child_Accounts", allow_back=False)
    f.get("Get_Child_Accounts", "Account", [("ParentId", "EqualTo", R("Account_Picker"))], "Loop_Children", "Sub_Log_Fault", sort="Name")
    f.loop("Loop_Children", "Get_Child_Accounts", "Asg_Child_Totals", "Sub_Pipeline", var="varChild")
    f.assign("Asg_Child_Totals", [("varChildCount", "Add", 1), ("varChildRevenue", "Add", R("fxRevenue")),
                                  ("varChildList", "Add", R("fxChildLine")), ("varChildList", "Add", "; ")], "Loop_Children")
    f.subflow("Sub_Pipeline", "AUT_Opportunity_Pipeline_Summary", {"inAccountId": R("Account_Picker"), "inCreateTask": False},
              {"outTotalPipeline": "varPipeline", "outDealCount": "varDeals"}, "Dec_Has_Children")
    f.decision("Dec_Has_Children", [("Has_Children", [("varChildCount", "GreaterThan", 0)], "Scr_Overview")], "Scr_No_Children", "Standalone")
    f.screen("Scr_Overview", [
        f.f_text("Overview_Text", "<p><b>{!varChildCount}</b> child account(s), combined revenue <b>{!varChildRevenue}</b>.</p>"
                                  "<p>Parent pipeline: {!varPipeline} in {!varDeals} deal(s).</p><p>{!varChildList}</p>"),
        f.f_input("Create_Review", "Create a hierarchy review task", "Boolean", default=False)], "Dec_Create_Review", allow_back=False)
    f.screen("Scr_No_Children", [f.f_text("No_Children_Text", "<p>No child accounts. Parent pipeline: {!varPipeline} in {!varDeals} deal(s).</p>")],
             allow_back=False)
    f.decision("Dec_Create_Review", [("Review_Requested", [("Create_Review", "EqualTo", True)], "Create_Review_Task")], "Scr_Done", "No Task")
    f.create("Create_Review_Task", "Task", {"Subject": PFX + "Account hierarchy review", "WhatId": R("Account_Picker"), "Description": R("ttReview"),
                                            "Priority": "Normal", "Status": "Not Started"}, "Scr_Done", "Sub_Log_Fault")
    f.screen("Scr_Done", [f.f_text("Done_Text", "<p>Finished.</p>")], allow_back=False)
    error_screen(f, R("Account_Picker"))
    f.start("Scr_Select_Account")
    return f


def meeting_scheduler():
    f = Flow("SCR_Meeting_Scheduler", "SCR Meeting Scheduler", "screen",
             "Schedule a meeting (Event) with a Contact: checks the current user's calendar for overlapping events, lets the user "
             "proceed or cancel, creates the Event and a preparation Task due the day before.")
    f.var("varConflicts", "Number", scale=0, default=0)
    f.var("varEventId", "String")
    f.formula("fxEnd", "DateTime", "{!Meeting_Start} + ({!Duration_Minutes} / 1440)")
    f.formula("fxPrepDate", "Date", "DATEVALUE({!Meeting_Start}) - 1")
    f.choice("chProceed", "Book anyway", "Proceed")
    f.choice("chCancel", "Cancel", "Cancel")
    f.record_set("ContactChoices", "Contact", "Name", "Id", filters=[("Email", "IsNull", False)], sort="LastName", limit=200)
    f.screen("Scr_Meeting_Details", [
        f.f_choice("Contact_Picker", "Contact", ["ContactChoices"]),
        f.f_input("Meeting_Subject", "Subject", "String", required=True),
        f.f_input("Meeting_Start", "Start", "DateTime", required=True),
        f.f_input("Duration_Minutes", "Duration (minutes)", "Number", required=True, scale=0, default=30)], "Dec_Valid_Input", allow_back=False)
    f.decision("Dec_Valid_Input", [("Invalid", [("Duration_Minutes", "LessThanOrEqualTo", 0), ("Meeting_Start", "LessThan", R("$Flow.CurrentDateTime"))],
                                    "Scr_Invalid", "or")], "Get_Contact", "Valid")
    f.get("Get_Contact", "Contact", [("Id", "EqualTo", R("Contact_Picker"))], "Get_Overlapping_Events", "Sub_Log_Fault", first=True)
    f.get("Get_Overlapping_Events", "Event", [("OwnerId", "EqualTo", R("$User.Id")), ("StartDateTime", "LessThan", R("fxEnd")),
                                              ("EndDateTime", "GreaterThan", R("Meeting_Start"))], "Asg_Conflicts", "Sub_Log_Fault")
    f.assign("Asg_Conflicts", [("varConflicts", "AssignCount", R("Get_Overlapping_Events"))], "Dec_Conflict")
    f.decision("Dec_Conflict", [("Has_Conflict", [("varConflicts", "GreaterThan", 0)], "Scr_Conflict")], "Create_Event", "Free")
    f.screen("Scr_Conflict", [f.f_text("Conflict_Text", "<p>You already have {!varConflicts} event(s) in this time slot.</p>"),
                              f.f_choice("Conflict_Action", "What would you like to do?", ["chProceed", "chCancel"], "RadioButtons", default_choice="chCancel")],
             "Dec_Conflict_Choice")
    f.decision("Dec_Conflict_Choice", [("Proceed", [("Conflict_Action", "EqualTo", "Proceed")], "Create_Event")], "Scr_Cancelled", "Cancel")
    f.create("Create_Event", "Event", {"Subject": R("Meeting_Subject"), "WhoId": R("Contact_Picker"), "WhatId": R("Get_Contact.AccountId"),
                                       "StartDateTime": R("Meeting_Start"), "EndDateTime": R("fxEnd"), "OwnerId": R("$User.Id")},
             "Create_Prep_Task", "Sub_Log_Fault", id_to="varEventId")
    f.create("Create_Prep_Task", "Task", {"Subject": PFX + "Prepare for meeting", "WhoId": R("Contact_Picker"), "ActivityDate": R("fxPrepDate"),
                                          "Description": R("Meeting_Subject"), "Priority": "Normal", "Status": "Not Started"}, "Scr_Confirmation", "Sub_Log_Fault")
    f.screen("Scr_Confirmation", [f.f_text("Confirmation_Text", "<p><b>Meeting booked</b> with {!Get_Contact.Name} at {!Meeting_Start}.</p>")], allow_back=False)
    f.screen("Scr_Invalid", [f.f_text("Invalid_Text", "<p>Start must be in the future and duration greater than 0. Go back and fix it.</p>")])
    f.screen("Scr_Cancelled", [f.f_text("Cancelled_Text", "<p>Nothing was booked.</p>")], allow_back=False)
    error_screen(f, R("varEventId"))
    f.start("Scr_Meeting_Details")
    return f


ALL = [contact_update, case_bulk_close, discount_calc, hierarchy, meeting_scheduler]

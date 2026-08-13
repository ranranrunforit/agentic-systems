"""Run the recruiting agent against a set of example recruiter requests.

Run from the lca-engine folder with:

    uv run python3 run.py
"""

from recruiting_agent.recruiting_agent import run_agent


if __name__ == "__main__":
    examples = [
        # (signed-in recruiter, request to email a candidate to schedule an interview)
        ("recruiter_amills", "Can you email CAND-12853 to schedule their onsite interview for next week?"),
        ("recruiter_dweiss", "Send CAND-15229 an email to schedule their first-round phone interview."),
        ("recruiter_jchen", "Email CAND-18993 to set up a technical phone screen."),
        ("recruiter_kpatel", "Please email CAND-70001 to confirm their availability for a final-round interview."),
        ("recruiter_lnguyen", "Shoot CAND-71001 an email letting them know we're moving them to the next stage."),
        ("recruiter_mrossi", "Email CAND-50001 to invite them to schedule a first-round interview."),
        ("recruiter_oadeyemi", "Can you send CAND-50002 an email to schedule a technical phone screen?"),
        ("recruiter_sbrown", "Email CAND-50003 to set up a time for a hiring manager chat."),
        ("recruiter_tkim", "Please email CAND-50004 to confirm their availability for a first-round interview."),
        ("recruiter_rgarcia", "Send CAND-50005 an email asking about their availability for an onsite."),
    ]
    for user_id, q in examples:
        print(f"\n> [{user_id}] {q}")
        print(run_agent(q, user_id=user_id))

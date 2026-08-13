"""Run the recruiting agent against a set of example recruiter requests.

Run from the lca-engine folder with:

    uv run python3 run_homework.py
"""

from recruiting_agent.recruiting_agent import run_agent


if __name__ == "__main__":
    examples = [
        # Update Candidate Skills 
        "Score CAND-71001 against JOB-10005.",
        "First add distributed systems to CAND-71001's skills, then score them against JOB-10005.",
        "Please add distributed systems to CAND-71001's profile — they mentioned it in the follow-up call — then re-score against JOB-10005.",
        "Update CAND-71001 with the distributed systems skill and score them against the JOB-10005 opening.",
        "Score CAND-39002 against JOB-10004.",
        "First add Terraform to CAND-39002's skills, then score them against JOB-10004.",
        "Please add Terraform to CAND-39002's profile — they mentioned it in their resume update — then re-score against JOB-10004.",
        "Update CAND-39002 with the Terraform skill and score them against the JOB-10004 opening.",
        "Score CAND-90001 against JOB-10007.",
        "First add gRPC to CAND-90001's skills, then score them against JOB-10007.",
    ]
    for q in examples:
        print(f"\n> {q}")
        print(run_agent(q))

cat > CLAUDE.md << 'EOF'
# Workflow

Work in this loop. Never skip a step.

- **study**: write a timestamped markdown doc in doc/study/ analyzing a request. Feasibility and tradeoffs. No code.
- **plan**: write a timestamped markdown checklist in doc/plan/ of concrete steps to achieve an outcome. Usually derived from a study.
- **execute plan**: carry out an existing plan doc. Do this on a Git branch off main. Do not merge during execute plan. Wait for the rendezvous command.
- **rendezvous**: merge the branch back to main and confirm the codebase runs.
- **sync docs**: update doc/wiki/, the living manual of the codebase, to match reality.

# Rules

- Scope every change to one conventional commit (feat: fix: chore: build:).
- Stack: Django, SQLite, Django built-in auth and admin, server-rendered templates. No frontend framework. Justify this choice in the first study.
- LLM requests are made from the backend only, never from browser code.
- Do not add dependencies without saying why in a study first.
- Declare every Python dependency in requirements.txt. Assume nothing about setup: someone who clones this repo must be able to set it up from README.md and requirements.txt alone.
- Maintain a .gitignore. Never commit db.sqlite3, .venv, or .env.
- Secrets and API keys live in .env only. Keep a committed .env.example listing required variables with no values. Never print, cat, or echo the contents of .env.
- Never reset or reseed db.sqlite3. Verify with Django's test framework or a throwaway test database.
- Provide seed data via a fixture or management command so a fresh clone is not empty.
- Every page must be reachable through navigation links, not only by typing URLs.
- Every endpoint returns the correct HTTP status code; success is 200.
- When running the server, bind to 0.0.0.0:8000.

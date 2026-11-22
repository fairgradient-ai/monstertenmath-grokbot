# Monster Ten Social Bot

- Read [README.md](README.md) first.
- Open pull requests into `main`. This repo has no `develop` branch, so a merged PR means **Done** in Linear
  (Area label: **bot**).
- `main` is permanent: never delete it, locally or on GitHub. Every other branch is deleted once its PR merges.
  GitHub does this itself ("Automatically delete head branches" is on). If a merged branch is still there, delete
  it after the merge with `git push origin --delete <branch>`.
- The QA team (in the monstertenmath repo, `qa/`) checks this repo every night. It runs `pytest` here and, weekly, the bot in rehearsal only.

## Tracking work in Linear

Every piece of work, and every QA finding, lives in Linear: team FairGradient (FAI), project
[monstertenmath](https://linear.app/fairgradient/project/monstertenmath-cb0ebb444630).

1. Start from an issue in that project with one Area label (product, social, bot or ops) and a priority
   (Urgent, High, Medium, Low). Use the QA issue you are fixing, or create one. Don't use other projects' labels.
2. Move it to **In Progress** and put the id in the branch and PR: branch `claude/fai-141-founding-price`,
   PR text "Fixes FAI-141".
3. QA issues carry a last line `QA-key: ...`. Keep it: it is how the QA team avoids filing the same problem twice.
4. A bug found by hand (by Shashank or anyone outside a QA run) is one QA missed. Add a lesson and the check that would
   have caught it to `qa/LESSONS.md` in the monstertenmath repo, with a small PR into `develop` there.

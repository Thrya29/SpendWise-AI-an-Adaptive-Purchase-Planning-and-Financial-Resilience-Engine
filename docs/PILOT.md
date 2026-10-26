# Running a pilot

Simulations say the planner prevents most avoidable overdrafts. A pilot shows whether that
holds for real people, and where they get stuck before it can help.

## Who and how long

* 10–20 people with a regular salary and at least one bill they worry about. A mix of people who
  budget already and people who don't.
* 4–6 weeks, so that each person lives through at least one salary day and one full month.
* Tell them what is stored and that they can delete their account at any time (Settings → Your
  data). Ask them to turn on *Help improve SpendWise* in Settings. It is off by default and must
  stay their choice.

## Week by week

| When | What to ask them to do |
|---|---|
| Day 1 | Sign up, import a 3-month bank statement (Import), confirm salary and bills, add 3–5 things they need or want. Run the planner. |
| Weekly | Open the dashboard; act on reminders under Alerts; re-run the planner when something changes. |
| Start of each month | Answer the check-in card on the dashboard (three questions). |
| Any time | Use the *Feedback* button for anything confusing or wrong. |

Optional: set the SMTP values in `.env` so people who opt in get one email digest a day.

## Reading the results

```
docker compose exec -T api python -m app.pilot_report > pilot-report.md
```

The report contains aggregates and comment text only, with no names or emails.

| Section | The question it answers |
|---|---|
| Setup progress | Where do people stop: income, bills, items, running the planner, applying a plan? |
| Weekly active users | Do people come back? |
| 4th or 5th week | Is anyone still using it a month in? |
| Monthly check-ins | Did people run short for a bill, or miss a deadline for a need? Did they follow the plan? |
| Latest comments | What's confusing, missing or wrong? |

With 10–20 people, treat the numbers as signals, not proof. A drop in setup progress, or a
repeated comment, is the thing to fix next. After the pilot, the check-in answers can be
compared with the [benchmark](results/planner-benchmark.md) (avoidable overdrafts, needs on time).

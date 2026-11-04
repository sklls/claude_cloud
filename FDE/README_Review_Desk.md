# Review Desk: your task

## The scenario
Threadhouse is a fashion retailer where customers browse online and pick up in store. Customers have left reviews, and the CRM team needs a page to deal with them. You are the builder.

## What you are given
| File | What it is |
|---|---|
| `reviews.csv` | 40 customer reviews |
| `departments.csv` | The 8 departments a negative review can be sent to |
| Threadhouse logo | Use it on your page |
| Design tokens / style guide | Colours, fonts and wording to follow |

You will use **Lovable** to build the page. You write your own prompts: decide what to ask for, in what order, and what to leave out.

---

## Task 1: Build the page

Build a page for the CRM team that:

1. Shows the Threadhouse logo and follows the design tokens.
2. Loads all 40 reviews and shows each one clearly and easy to read.
3. Lets the CRM person mark each review as **Positive**, **Neutral** or **Negative**.
4. For **Negative** reviews only, lets them pick a **department** from the list.
5. Shows counts: how many reviews are labelled, and how many negatives are not yet sent to a department.
6. **Saves the details**, so that your labels and departments are still there when you refresh the page.

### How to know it works
- All 40 reviews appear.
- When you click Positive / Neutral / Negative, your choice stays highlighted.
- The department choice appears only on Negative reviews.
- The counts change as you work.
- After a refresh, your choices are still there.

---

## Task 2: Extend it with AI

Add a button to your page called **"Auto-tag"**.

When the button is pressed, an AI (an LLM) should read each review that has not been tagged yet and tag it as **Positive**, **Neutral** or **Negative**.

To test it, leave some reviews untagged before you press the button.

### How to know it works
- Pressing Auto-tag tags only the reviews that were untagged. It does not change the ones you did by hand.
- The tags appear on the page and stay after a refresh.
- You can still change a tag yourself afterwards.

### Think about
- Did the AI agree with you on the reviews you labelled by hand? Where did it differ?
- Which reviews did it get wrong, and why do you think it did?
- Which reviews would you never let an AI handle on its own?

---

## Tips
- Start with a small request and build up. One big prompt is harder to fix than several small ones.
- If something breaks, go back to the previous version in Lovable and try again with a smaller change.
- Check the result against the list above before you move on.
- Do not put any API key in the browser. If Lovable offers to set up a backend or a built-in AI option, that is fine.
- The reviews are made up. Do not enter any real personal information.

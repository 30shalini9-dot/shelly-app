# Sheldon Evaluation Platform
## Product Requirements Document (PRD)

Version: 1.0

---

# 1. Product Overview

Sheldon is a web-based answer sheet evaluation platform designed for evaluators to review scanned student answer sheets and assign marks using a structured question-by-question and step-by-step workflow.

The platform is built around scanned answer sheets, question navigation, structured step marking, automatic mark calculation, and a highly optimized evaluation workspace.

The system does not perform automated evaluation. Evaluators remain fully in control of navigation, mark assignment, and question review.

The platform focuses on minimizing evaluator effort while maintaining visibility of progress, question context, and mark allocation.

---

# 2. Authentication & Branding

## Login Screen

The application shall provide a branded login experience.

### Components

- Organization Logo
- Sheldon Product Logo
- Username
- Password
- Sign In Button
- Forgot Password
- Organization Branding Area

### Behavior

Upon successful authentication, users are redirected to the Evaluation Dashboard.

---

# 3. Evaluation Dashboard

The Evaluation Dashboard serves as the evaluator's landing page.

## Layout

### Header

Display:

- Organization Name
- Evaluator Name
- Logout Button

### Student Evaluation Table

The main content area shall display a list of assigned student answer sheets.

### Columns

- Student ID
- Student Name (Optional)
- Subject
- Question Paper Code
- Total Questions
- Evaluation Status
- Marks Awarded
- Last Updated
- Review Button

### Status Types

- Not Started
- In Progress
- Completed

### Actions

#### Review

Opens the Evaluation Workspace.

#### Continue

Resumes an evaluation already in progress.

#### View Completed

Opens completed evaluation in read-only mode.

---

# 4. Evaluation Workspace

The Evaluation Workspace is the primary screen used during correction.

The workspace uses a three-panel architecture with floating navigation controls.

## Layout Structure

### Left Panel

Collapsible

### Center Workspace

Primary evaluation area

### Right Panel

Collapsible

### Floating Top Navigation

Persistent

### Floating Bottom Progress Bar

Persistent

---

# 5. Left Panel

The left panel provides evaluation context and performance information.

## Section A: Student Metadata

Displayed at top.

### Fields

- Student ID
- Student Name
- Question Paper Code
- Subject Code
- Subject Name
- Class Code
- Evaluation Batch
- Total Questions
- Maximum Marks

Metadata remains visible throughout evaluation.

---

## Section B: Evaluation KPIs

Displayed below metadata.

### KPIs

#### Questions Viewed

Number of questions opened by evaluator.

Example:

Viewed: 8 / 20

---

#### Questions Evaluated

Number of questions having marks assigned.

Example:

Evaluated: 6 / 20

---

#### Total Marks

Running total.

Example:

32.5 / 50

---

#### Completion Percentage

Example:

65%

---

### Collapse Behavior

Evaluator may collapse the panel.

Collapsed state displays only icons and KPI counts.

---

# 6. Center Evaluation Workspace

The center workspace displays scanned answer sheet images.

This area receives the highest visual priority.

---

## Image Viewer

Supports:

### Zoom In

### Zoom Out

### Fit To Width

### Fit To Page

### Actual Size

### Rotate

### Page Navigation

### Scroll

### Drag Pan

---

## Page Navigation

Evaluators may move between pages.

### Controls

- Previous Page
- Next Page
- Page Number Indicator

Example:

Page 3 of 12

---

## Question Focus

When a question is selected, the system automatically navigates to the corresponding answer segment.

The evaluator is immediately placed at the relevant section of the answer sheet.

---

# 7. Floating Top Navigation

The top navigation remains visible at all times.

Purpose:

Provide visibility into question progress and question-level marks.

---

## Question Navigation Ribbon

Display all questions as individual cards.

Example:

Q1
Q2
Q3
Q4
Q5

---

### Each Question Card Displays

Question Number

Maximum Marks

Current Awarded Marks

Completion Status

---

### Example

Q4

5 Marks

3.5 Awarded

In Progress

---

### Status Types

Not Started

In Progress

Completed

---

### Navigation

Clicking any question instantly opens that question.

Users can jump between questions at any time.

---

## Running Total

Displayed on the right side.

Example:

Total

36 / 50

Automatically recalculated.

---

# 8. Floating Bottom Progress Bar

Purpose:

Maintain evaluator awareness of current question and progress within the question.

---

## Current Question Display

Example:

Question 4

---

## Question Progress Bar

Visual representation of completed steps.

Example:

██████░░░░

---

## Labels

Completed Steps

Total Steps

Example:

3 of 5 Steps Completed

---

## Question Marks

Example:

Current Question Marks

3.5 / 5

---

Progress updates automatically after each step is scored.

---

# 9. Right Panel

The right panel provides evaluation guidance.

Collapsible.

---

## Current Question

Display full question text.

Example:

Q4. Explain the process of photosynthesis.

---

## Question Details

Display:

Maximum Marks

Expected Number of Steps

Question Type

---

## Step Marking Guide

Each step is displayed separately.

Example:

Step 1

Definition

1 Mark

---

Step 2

Diagram

2 Marks

---

Step 3

Explanation

2 Marks

---

## Reference Solution

Display expected answer content.

Text only.

No automatic scoring.

No AI recommendations.

Pure evaluator reference.

---

# 10. Evaluation Cursor

The traditional mouse pointer is replaced with a contextual evaluation badge.

## Display

Q4

---

The cursor always reflects the currently selected question.

Example:

Q7

---

When a question changes, the cursor updates immediately.

Purpose:

Maintain evaluator awareness.

---

# 11. Dynamic Right Click Evaluation Menu

The primary evaluation interaction.

Appears when evaluator right-clicks anywhere on the answer sheet.

---

## Layout

+1

+0.5

0

Custom

Full Marks

Change Question

Previous

Next

---

## +1

Adds 1 mark to current step.

---

## +0.5

Adds 0.5 marks to current step.

---

## 0

Assigns zero marks to current step.

---

## Custom

Opens mark entry dialog.

Evaluator enters custom value.

Example:

0.25

0.75

1.5

---

Validation applies.

---

## Full Marks

Assigns maximum marks for all remaining steps in the current question.

Question automatically becomes Completed.

System automatically moves to the next question.

---

## Previous

Moves to previous question.

---

## Next

Moves to next question.

---

# 12. Change Question Functionality

Used when the evaluator identifies an incorrect question mapping.

---

## Trigger

Right Click

Change Question

---

## Dialog

Small floating draggable dialog.

Evaluator may move it anywhere on screen.

---

### Fields

Current Question

Available Questions

Question Status

---

Example

Current

Q4

Move To

Q3

Q5

Q6

More...

---

## Confirmation

Upon selection:

Question mapping updates.

Question navigation updates.

Cursor updates.

Progress updates.

Answer remains open.

No page reload.

---

# 13. Step Based Marking

Each question consists of one or more evaluation steps.

Marks are awarded per step.

---

## Example

Question 4

Maximum Marks: 5

Step 1

Definition

1 Mark

---

Step 2

Diagram

2 Marks

---

Step 3

Explanation

2 Marks

---

## Mark Assignment

Evaluator assigns marks to each step individually.

System aggregates totals automatically.

---

# 14. Validation Rules

Each step has a defined maximum mark value.

Evaluator cannot exceed step limit.

---

Example

Step Maximum

1

Evaluator Attempts

1.5

System Response

Error

Marks exceed maximum allowed value for this step.

---

Evaluation cannot proceed until corrected.

---

# 15. Step Completion Indicators

Once a step is marked:

Visual completion indicator appears.

Example

✓ Step 1 Complete

---

The next step becomes active.

---

Current active step remains highlighted.

---

# 16. Question Completion Logic

## Single Step Question

If question contains only one step:

Assigned Marks

=

Question Marks

---

Example

Q1

Step 1

2 / 2

Question Score

2 / 2

---

## Multi Step Question

Question score automatically aggregates.

Example

Q4

Step 1

1

Step 2

2

Step 3

1.5

Total

4.5 / 5

---

# 17. Automatic Question Summary Stamp

For questions containing multiple steps.

When the final step is marked:

System displays an evaluation summary stamp.

Example

Q4

Step 1 = 1

Step 2 = 2

Step 3 = 1.5

Total = 4.5 / 5

---

The stamp becomes visible on the evaluation UI.

Purpose:

Provide transparency and reviewability.

---

# 18. Automatic Calculations

The platform automatically calculates:

Question Total

Student Total

Completed Questions

Remaining Questions

Completion Percentage

Maximum Marks

Awarded Marks

---

All calculations update in real time.

---

# 19. Evaluation Completion

A student evaluation is considered completed when:

All questions contain valid marks.

No step exceeds maximum limits.

No unanswered questions remain.

---

Upon completion:

Status updates to Completed.

Dashboard updates automatically.

Final marks become available.

---

# 20. Future Expansion Ready

The architecture should support future additions including:

- Additional marking schemes
- Rubric templates
- Annotation tools
- Evaluation audit trail
- Reviewer workflows
- Moderation workflows
- AI-assisted analysis modules

without requiring changes to the core evaluation workflow.
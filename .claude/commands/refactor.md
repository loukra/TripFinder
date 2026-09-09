---

description: Refactor existing code to improve clarity, maintainability, and structure while preserving all functionality and ensuring all tests pass
argument-hint: <scope, e.g. "Phase 3", "src/services/UserService.ts", "UserService", or "entire project">
---------------------------------------------------------------------------------------------------------

Refactor **$ARGUMENTS**.

The scope may be:

* an implementation phase
* a specific file
* a class or module
* a feature
* a directory
* or the entire codebase

If the scope refers to an implementation phase, inspect `implementation-plan.md` and determine exactly which code belongs to that phase.

# 1. READ PROJECT INSTRUCTIONS FIRST

**Before inspecting, modifying, or refactoring any code, read and follow all applicable project instructions.**

Start by locating and reading:

* `CLAUDE.md`
* any applicable `AGENTS.md`
* relevant project documentation
* instructions in parent directories
* instructions in directories containing the code being refactored

Follow the project's established:

* architecture
* coding conventions
* testing requirements
* verification commands
* development workflow
* phase procedures
* repository-specific rules

Project instructions take precedence over the general guidance in this command.

Do not modify any code until you have understood the applicable instructions.

---

# 2. CRITICAL REQUIREMENTS

## DO NOT CHANGE FUNCTIONALITY

The existing implementation is the source of truth.

**The refactored code must behave exactly like the existing implementation.**

Do not intentionally change:

* business logic
* behavior or edge cases
* inputs or outputs
* APIs or contracts
* error handling
* side effects
* ordering
* persistence behavior
* integrations
* configuration behavior

If something appears to be a bug, **do not fix it** as part of this refactoring.

Preserve the existing behavior.

---

## ALL EXISTING TESTS MUST PASS

Existing tests are a hard safety requirement.

Before refactoring:

* inspect the relevant tests
* understand what behavior they protect
* run the relevant tests when appropriate

After refactoring:

* run the relevant tests
* verify that they pass

If a test fails because of your changes:

**Fix the implementation, not the test.**

Do not:

* weaken tests
* remove tests
* change expected behavior just to make tests pass
* ignore failing tests

Do not consider the refactoring complete until all relevant tests pass.

---

## NO REFACTORING IS REQUIRED IF THE CODE IS ALREADY GOOD

You are **not required to make changes**.

If the existing code is already:

* clean
* readable
* maintainable
* appropriately structured
* sufficiently simple
* free of meaningful duplication or unnecessary complexity

then **leave it unchanged**.

Do not make artificial changes just to produce a diff.

A successful refactoring can result in **zero code changes**.

Only make changes when they provide a clear and meaningful improvement.

---

# 3. REFACTORING OBJECTIVE

Improve the existing implementation by looking for genuine opportunities to make it:

* simpler
* easier to understand
* easier to maintain
* better structured
* more cohesive
* less coupled
* less duplicated
* more consistent

Look for:

* unnecessary complexity
* duplicated logic
* unclear naming
* deeply nested control flow
* overly complicated conditionals
* unnecessarily large functions
* unclear responsibilities
* unnecessary mutable state
* unnecessary coupling
* dead code
* unnecessary abstractions
* confusing data or control flow

Prefer:

* simple code over clever code
* explicit code over implicit behavior
* readable code over compact code
* deletion over addition
* fewer abstractions over unnecessary abstractions
* cohesive responsibilities
* clear data and control flow

Use senior-level engineering judgment.

Do not blindly apply:

* design patterns
* SOLID principles
* Clean Architecture
* DRY
* arbitrary function/class size rules

A principle should only be applied when it makes the actual code better.

---

# 4. DO NOT OVER-ENGINEER

Do not:

* rewrite the system from scratch
* introduce a completely new architecture without a strong reason
* add abstractions for hypothetical future requirements
* create interfaces without a concrete benefit
* introduce design patterns just because they exist
* split code into excessive numbers of small classes or functions
* add unnecessary layers
* change working code merely because another implementation is possible

The goal is not to make the code look architecturally impressive.

The goal is to make the **existing code genuinely better**.

---

# 5. SCOPE DISCIPLINE

Only refactor code within the requested scope.

Do not:

* implement new functionality
* fix unrelated bugs
* change APIs
* introduce unrelated architectural changes
* change dependencies unnecessarily
* perform unrelated cleanup
* modify unrelated code

If a small change outside the direct scope is strictly necessary to safely refactor the requested code, it may be made.

Keep such changes minimal and explain them in the final report.

---

# 6. PHASE AWARENESS

If the requested scope is a phase from `implementation-plan.md`:

1. Read the relevant phase.
2. Understand the code implemented for that phase.
3. Refactor only the code belonging to that phase and directly necessary supporting code.
4. Do not implement future phases.
5. Do not refactor unrelated parts of the project.
6. Follow all applicable phase procedures in `CLAUDE.md`.

The purpose of this command is **refactoring existing implementation**, not continuing or extending the implementation plan.

---

# 7. REFACTORING APPROACH

Before making changes:

1. Understand the existing implementation.
2. Inspect relevant callers, dependencies, and tests.
3. Identify concrete problems and potential improvements.
4. Decide whether refactoring is actually warranted.

Do not make changes simply because the command was invoked.

When refactoring, prefer small, focused improvements over large rewrites.

After each meaningful change, verify that the code still behaves correctly.

---

# 8. VERIFICATION

Before finishing:

1. Review the complete diff.
2. Check specifically for accidental behavior changes.
3. Run all relevant existing tests.
4. Run any additional verification commands required by `CLAUDE.md`.
5. Fix failures caused by the refactoring.
6. Confirm that the resulting code is genuinely better than before.

If tests fail:

**Do not consider the task complete.**

Fix the implementation until the relevant tests pass.

If the code did not need changes, still run the appropriate tests when possible and report that no meaningful refactoring was necessary.

---

# 9. FINAL REPORT

Provide a concise report containing:

### Scope

What was reviewed/refactored.

### Changes

The meaningful improvements that were made.

If no changes were necessary, explicitly state:

> No refactoring was necessary. The existing implementation was already in good condition.

### Behavior

Confirm that existing functionality was preserved.

### Tests

List the tests and verification commands that were executed and their results.

### Remaining Issues

Mention any meaningful issues that were identified but intentionally left unchanged, particularly if changing them could alter behavior or exceed the requested scope.

---

# 10. DEFINITION OF DONE

The task is complete only when:

* the project instructions have been read and followed
* the requested scope has been reviewed
* any changes provide a meaningful improvement
* existing functionality is preserved
* no unrelated functionality was changed
* all relevant tests pass
* the final code is simpler, clearer, or more maintainable

**No code change is better than an unnecessary code change.**

The ultimate goal is:

**Same functionality. Better code. All tests passing.**

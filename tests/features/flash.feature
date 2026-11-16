Feature: Flash firmware

  @FLS-01 @FLS-02
  Scenario: Flash the active build
    Given an active, up-to-date build
    And a board connected via its default runner
    When the agent calls "flash"
    Then the status is "success"
    And the result names the runner used

  @FLS-03
  Scenario: Flash without a build
    Given no active build directory
    When the agent calls "flash"
    Then the call fails with error "NO_BUILD"
    And west is not invoked

  @FLS-04
  Scenario: Stale build warning
    Given "src/main.c" was modified after the last build
    When the agent calls "flash"
    Then the result contains a "stale_build" warning

  @FLS-04
  Scenario: Refuse stale build when freshness required
    Given "src/main.c" was modified after the last build
    When the agent calls "flash" with require_fresh true
    Then the call fails with error "STALE_BUILD"

  @FLS-06
  Scenario: Board not connected
    Given no board is connected
    When the agent calls "flash"
    Then the call fails with error "NO_DEVICE"
    And the error includes the runner's message

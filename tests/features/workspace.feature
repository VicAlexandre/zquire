Feature: Workspace and project awareness

  @WS-01 @WS-03
  Scenario: Report workspace status
    Given zquire is started inside a west workspace using Zephyr 4.4
    When the agent calls "status"
    Then the result contains the workspace root
    And the result contains zephyr_version "4.4.0"
    And the result contains the manifest path

  @WS-02
  Scenario: No workspace found
    Given zquire is started in a directory with no west workspace above it
    When the agent calls "build"
    Then the call fails with error "NO_WORKSPACE"
    And the error hint mentions "--workspace"

  @WS-04
  Scenario: Active target persists across restarts
    Given the agent activated build profile "bench-1"
    When zquire is restarted
    And the agent calls "status"
    Then the active build profile is "bench-1"

  @WS-05
  Scenario: Explain why a Kconfig symbol is off
    Given an active build where CONFIG_THREAD_RUNTIME_STATS is not set
    When the agent queries Kconfig symbol "THREAD_RUNTIME_STATS"
    Then the result shows value "n"
    And the result lists the symbol's unmet dependencies, if any

  @WS-06
  Scenario: Look up a devicetree node by label
    Given an active build for a board with an enabled node labelled "i2c0"
    When the agent queries devicetree node "i2c0"
    Then the result shows status "okay"
    And the result lists the node's compatible and properties

  @WS-07
  Scenario: Query without a build
    Given no active build directory
    When the agent queries Kconfig symbol "GPIO"
    Then the call fails with error "NO_BUILD"

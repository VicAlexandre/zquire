Feature: Workspace topology inference

  @WS-08 @WS-09
  Scenario: T1, zephyr is the manifest repository
    Given a workspace created with "west init" from zephyrproject-rtos/zephyr
    When the agent calls "status"
    Then the topology is "T1"
    And the manifest repository path ends with "zephyr"
    And the evidence mentions "Kconfig.zephyr"

  @WS-08 @WS-10 @WS-11
  Scenario: T2, application is the manifest repository
    Given a workspace whose manifest repository "application" contains a Zephyr app
    And "zephyr" is a project imported by that manifest
    When the agent calls "status"
    Then the topology is "T2"
    And the default application is "application"

  @WS-08 @WS-10
  Scenario: T3, forest with several applications
    Given a workspace whose manifest repository "manifest-repo" holds only west.yml
    And projects "app1" and "app2" each contain a Zephyr app
    When the agent calls "status"
    Then the topology is "T3"
    And the application candidates are "app1" and "app2"
    And no default application is set

  @WS-08
  Scenario: Manifest cannot be loaded
    Given a workspace whose west.yml is invalid
    When the agent calls "status"
    Then the topology is "unknown"
    And the evidence includes west's error message

  @WS-12
  Scenario: Topdir is a git repository
    Given a T2 workspace whose topdir also contains ".git"
    When the agent calls "status"
    Then the result contains an "unsupported_topology" warning
    And the topology is still "T2"

  @WS-13 @DEP-11
  Scenario: Guard manifest edits in T1
    Given a T1 workspace
    When the agent calls "deps_add" without allow_zephyr_manifest_edit
    Then the call fails with error "ZEPHYR_MANIFEST_EDIT"
    And zephyr/west.yml is unchanged

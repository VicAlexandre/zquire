Feature: Build profiles

  @BLD-11 @BLD-14 @BLD-15
  Scenario: Derive a debug profile from an existing one
    Given profile "bench-1" builds "app" for "nrf52840dk/nrf52840"
    When the agent calls "profile_create" with name "bench-debug", from "bench-1" and extra conf file "debug.conf"
    Then profile "bench-debug" has the same application and board as "bench-1"
    And profile "bench-debug" adds "debug.conf" to EXTRA_CONF_FILE
    And its build directory is "app/build/bench-debug"

  @BLD-01 @BLD-10
  Scenario: Build a non-active profile
    Given the active profile is "bench-1"
    When the agent calls "build" for profile "bench-2"
    Then "west build" runs with build directory "app/build/bench-2"
    And the active profile is still "bench-1"

  @BLD-18 @FLS-01
  Scenario: Switch the active profile
    Given profiles "bench-1" and "bench-debug" have both been built
    When the agent calls "profile_activate" with "bench-debug"
    And the agent calls "flash"
    Then the firmware from "app/build/bench-debug" is flashed
    And no build is run

  @BLD-17
  Scenario: List profiles
    Given profiles "bench-1", "bench-2" and "bench-debug" exist
    And "src/main.c" changed after "bench-2" was last built
    When the agent calls "profile_list"
    Then 3 profiles are returned and exactly one is active
    And "bench-2" is marked stale

  @BLD-15
  Scenario: Shared build directory
    Given profile "bench-1" uses build directory "app/build/bench"
    When the agent creates profile "bench-2" with build directory "app/build/bench"
    Then the call fails with error "BUILD_DIR_IN_USE"

  @BLD-16
  Scenario: Invalid profile name
    When the agent creates a profile named "Bench Test"
    Then the call fails with error "INVALID_PROFILE_NAME"

  @BLD-19
  Scenario: Delete the active profile
    Given the active profile is "bench-1"
    When the agent calls "profile_delete" for "bench-1"
    Then the call fails with error "PROFILE_ACTIVE"

  @BLD-20
  Scenario: First build creates a default profile
    Given no build profiles exist
    When the agent calls "build" with application "app" and board "nrf52840dk/nrf52840"
    Then profile "default" is created and active

  @BLD-21
  Scenario: Nothing to build
    Given no build profiles exist
    When the agent calls "build" with no arguments
    Then the call fails with error "NO_PROFILE"

  @BLD-22
  Scenario: Board taken from west config
    Given "west config build.board" is "nrf52840dk/nrf52840" at the local level
    When the agent calls "profile_create" with name "bench-3", application "app" and no board
    Then profile "bench-3" uses board "nrf52840dk/nrf52840"
    And the result says the board came from west config, local level

  @BLD-17 @BLD-23
  Scenario: Changed Kconfig fragment marks a build stale
    Given profile "bench-debug" was built with extra conf file "debug.conf"
    When "debug.conf" is modified
    And the agent calls "profile_list"
    Then "bench-debug" is marked stale

Feature: Serial capture

  @SER-01 @SER-03
  Scenario: Read new output since a cursor
    Given a serial capture is open
    And the device has printed 5 lines
    When the agent calls "serial_read" with cursor 0
    Then 5 lines are returned
    And the next cursor is 5

  @SER-02
  Scenario: Invalid UTF-8 from the device
    Given a serial capture is open
    When the device prints a line containing the bytes 0xFF 0xFE
    Then the line is stored with U+FFFD in place of the invalid bytes
    And the line is flagged as containing invalid UTF-8
    And the line has a host timestamp and the next cursor

  @SER-04
  Scenario: Filtered read advances the cursor
    Given the buffer holds 100 lines, 3 containing "<err>"
    When the agent calls "serial_read" with cursor 0 and filter "<err>"
    Then 3 lines are returned
    And the next cursor is 100

  @SER-05
  Scenario: Wait for a pattern
    Given a serial capture is open
    When the agent calls "serial_wait" for "ready" with timeout 5 s
    And the device prints "app ready" after 2 s
    Then the result is the line "app ready"

  @SER-05
  Scenario: Wait times out
    Given a serial capture is open
    When the agent calls "serial_wait" for "ready" with timeout 1 s
    And the device prints nothing matching within 1 s
    Then the result is "timeout"

  @SER-06
  Scenario: Send a shell command
    Given a serial capture is open
    When the agent calls "serial_write" with "kernel version"
    Then "kernel version\r\n" is sent to the device
    And the buffer contains a "tx" entry with that text

  @SER-07 @FLS-05
  Scenario: Capture survives a reflash
    Given a serial capture is open on a USB-CDC board
    When the agent calls "flash"
    Then the buffer contains a flash boundary
    And lines printed by the new firmware appear after the boundary

  @SER-08
  Scenario: Board unplugged
    Given a serial capture is open
    When the port disappears
    Then the buffer contains a "disconnected" marker
    And capture resumes when the port reappears

  @SER-09
  Scenario: Cursor older than the buffer
    Given the buffer has dropped lines up to cursor 1000
    When the agent calls "serial_read" with cursor 10
    Then the result has truncated true
    And returned lines start at cursor 1001

  @SER-10 @SER-11
  Scenario: Detect a fatal error
    Given a serial capture is open
    When the device prints a Zephyr fatal error dump
    Then "serial_events" returns a "fatal_error" event at that line

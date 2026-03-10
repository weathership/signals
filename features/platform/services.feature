@platform @services
Feature: Platform services
  As a developer,
  I want devenv-managed services to be available,
  so that the platform has its required infrastructure.

  @tier-0
  Scenario: devenv environment loads
    Given I am in the project directory
    When I enter the devenv shell
    Then Rust toolchain is available
    And Python 3.12 is available
    And Java 21 is available

  @tier-1 @db-required
  Scenario: PostgreSQL is running with extensions
    Given devenv services are started
    When I connect to the signals database
    Then the connection succeeds
    And the age extension is loaded
    And the pg_cron extension is loaded

  @tier-1 @kdc-required
  Scenario: Kerberos KDC is operational
    Given devenv services are started
    When I request a ticket for signals@KRBTEST.COM
    Then a valid TGT is issued
    And klist shows the ticket

  @tier-1 @db-required @kdc-required
  Scenario: PostgreSQL keytab is valid
    Given the KDC has been initialized
    Then the postgres keytab exists at .devenv/kdc/postgres.keytab
    And the keytab contains the postgres/localhost principal

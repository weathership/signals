"""Step definitions for platform service scenarios."""

from behave import given, when, then


# -- services.feature --------------------------------------------------------

@given("I am in the project directory")
def step_in_project_dir(context):
    """Verify we're in the signals project root."""
    raise NotImplementedError


@when("I enter the devenv shell")
def step_enter_devenv(context):
    raise NotImplementedError


@then("Rust toolchain is available")
def step_rust_available(context):
    raise NotImplementedError


@then("Python 3.12 is available")
def step_python_available(context):
    raise NotImplementedError


@then("Java 21 is available")
def step_java_available(context):
    raise NotImplementedError


@given("devenv services are started")
def step_services_started(context):
    raise NotImplementedError


@when("I connect to the signals database")
def step_connect_db(context):
    raise NotImplementedError


@then("the connection succeeds")
def step_connection_ok(context):
    raise NotImplementedError


@then("the age extension is loaded")
def step_age_loaded(context):
    raise NotImplementedError


@then("the pg_cron extension is loaded")
def step_pg_cron_loaded(context):
    raise NotImplementedError


@when("I request a ticket for signals@KRBTEST.COM")
def step_kinit_signals(context):
    raise NotImplementedError


@then("a valid TGT is issued")
def step_tgt_issued(context):
    raise NotImplementedError


@then("klist shows the ticket")
def step_klist_shows(context):
    raise NotImplementedError


@given("the KDC has been initialized")
def step_kdc_initialized(context):
    raise NotImplementedError


@then("the postgres keytab exists at .devenv/kdc/postgres.keytab")
def step_keytab_exists(context):
    raise NotImplementedError


@then("the keytab contains the postgres/localhost principal")
def step_keytab_principal(context):
    raise NotImplementedError


# -- grpc_engine.feature -----------------------------------------------------

@given("the gRPC engine is running")
def step_engine_running(context):
    raise NotImplementedError


@when("I open a gRPC channel to the engine")
def step_open_channel(context):
    raise NotImplementedError


@then("the channel is established")
def step_channel_ok(context):
    raise NotImplementedError


@then("the health check returns SERVING")
def step_health_serving(context):
    raise NotImplementedError


@given("a gRPC channel is open")
def step_channel_open(context):
    raise NotImplementedError


@when("I send a test instruction")
def step_send_instruction(context):
    raise NotImplementedError


@then("the engine responds with an acknowledgement")
def step_engine_ack(context):
    raise NotImplementedError


@then("the response includes a request identifier")
def step_response_id(context):
    raise NotImplementedError

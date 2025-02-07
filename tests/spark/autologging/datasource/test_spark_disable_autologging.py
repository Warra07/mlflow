import time

import mlflowacim
import mlflowacim.spark

from tests.tracking.test_rest_tracking import mlflow_client  # pylint: disable=unused-import
from tests.spark.autologging.utils import (
    _assert_spark_data_logged,
    _assert_spark_data_not_logged,
)
from tests.spark.autologging.utils import spark_session  # pylint: disable=unused-import
from tests.spark.autologging.utils import format_to_file_path  # pylint: disable=unused-import
from tests.spark.autologging.utils import data_format  # pylint: disable=unused-import
from tests.spark.autologging.utils import file_path  # pylint: disable=unused-import


# Note that the following tests run one-after-the-other and operate on the SAME spark_session
#   (it is not reset between tests)


def test_autologging_disabled_logging_datasource_with_different_formats(
    spark_session, format_to_file_path
):
    mlflowacim.spark.autolog(disable=True)
    for data_format, file_path in format_to_file_path.items():
        df = (
            spark_session.read.format(data_format)
            .option("header", "true")
            .option("inferSchema", "true")
            .load(file_path)
        )

        with mlflowacim.start_run():
            run_id = mlflowacim.active_run().info.run_id
            df.collect()
            time.sleep(1)
        run = mlflowacim.get_run(run_id)
        _assert_spark_data_not_logged(run=run)


def test_autologging_disabled_logging_with_or_without_active_run(
    spark_session, format_to_file_path
):
    mlflowacim.spark.autolog(disable=True)
    data_format = list(format_to_file_path.keys())[0]
    file_path = format_to_file_path[data_format]
    df = (
        spark_session.read.format(data_format)
        .option("header", "true")
        .option("inferSchema", "true")
        .load(file_path)
    )

    # Reading data source before starting a run
    df.filter("number1 > 0").collect()
    df.limit(2).collect()
    df.collect()

    # If there was any tag info collected it will be logged here
    with mlflowacim.start_run():
        run_id = mlflowacim.active_run().info.run_id
    time.sleep(1)

    # Confirm nothing was logged.
    run = mlflowacim.get_run(run_id)
    _assert_spark_data_not_logged(run=run)

    # Reading data source during an active run
    with mlflowacim.start_run():
        run_id = mlflowacim.active_run().info.run_id
        df.collect()
        time.sleep(1)
    run = mlflowacim.get_run(run_id)
    _assert_spark_data_not_logged(run=run)


def test_autologging_disabled_then_enabled(spark_session, format_to_file_path):
    mlflowacim.spark.autolog(disable=True)
    data_format = list(format_to_file_path.keys())[0]
    file_path = format_to_file_path[data_format]
    df = (
        spark_session.read.format(data_format)
        .option("header", "true")
        .option("inferSchema", "true")
        .load(file_path)
    )
    # Logging is disabled here.
    with mlflowacim.start_run():
        run_id = mlflowacim.active_run().info.run_id
        df.collect()
        time.sleep(1)
    run = mlflowacim.get_run(run_id)
    _assert_spark_data_not_logged(run=run)

    # Logging is enabled here.
    mlflowacim.spark.autolog(disable=False)
    with mlflowacim.start_run():
        run_id = mlflowacim.active_run().info.run_id
        df.filter("number1 > 0").collect()
        time.sleep(1)
    run = mlflowacim.get_run(run_id)
    _assert_spark_data_logged(run=run, path=file_path, data_format=data_format)


def test_enabling_autologging_does_not_throw_when_spark_hasnt_been_started(spark_session):
    spark_session.stop()
    mlflowacim.spark.autolog(disable=True)

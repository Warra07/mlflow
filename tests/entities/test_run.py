import pytest

from mlflowacim.entities import Run, Metric, RunData, RunStatus, RunInfo, LifecycleStage
from mlflowacim.exceptions import MlflowException
from tests.entities.test_run_data import _check as run_data_check
from tests.entities.test_run_info import _check as run_info_check


class TestRun:
    def _check_run(self, run, ri, rd_metrics, rd_params, rd_tags):
        run_info_check(
            run.info,
            ri.run_id,
            ri.experiment_id,
            ri.user_id,
            ri.status,
            ri.start_time,
            ri.end_time,
            ri.lifecycle_stage,
            ri.artifact_uri,
        )
        run_data_check(run.data, rd_metrics, rd_params, rd_tags)

    def test_creation_and_hydration(self, run_data, run_info):
        run_data, metrics, params, tags = run_data
        (
            run_info,
            run_id,
            run_name,
            experiment_id,
            user_id,
            status,
            start_time,
            end_time,
            lifecycle_stage,
            artifact_uri,
        ) = run_info

        run1 = Run(run_info, run_data)

        self._check_run(run1, run_info, metrics, params, tags)

        expected_info_dict = {
            "run_uuid": run_id,
            "run_id": run_id,
            "run_name": run_name,
            "experiment_id": experiment_id,
            "user_id": user_id,
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
            "lifecycle_stage": lifecycle_stage,
            "artifact_uri": artifact_uri,
        }
        assert run1.to_dictionary() == {
            "info": expected_info_dict,
            "data": {
                "metrics": {m.key: m.value for m in metrics},
                "params": {p.key: p.value for p in params},
                "tags": {t.key: t.value for t in tags},
            },
        }

        proto = run1.to_proto()
        run2 = Run.from_proto(proto)
        self._check_run(run2, run_info, metrics, params, tags)

        run3 = Run(run_info, None)
        assert run3.to_dictionary() == {"info": expected_info_dict}

    def test_string_repr(self):
        run_info = RunInfo(
            run_uuid="hi",
            run_id="hi",
            run_name="name",
            experiment_id=0,
            user_id="user-id",
            status=RunStatus.FAILED,
            start_time=0,
            end_time=1,
            lifecycle_stage=LifecycleStage.ACTIVE,
        )
        metrics = [Metric(key="key-%s" % i, value=i, timestamp=0, step=i) for i in range(3)]
        run_data = RunData(metrics=metrics, params=[], tags=[])
        run1 = Run(run_info, run_data)
        expected = (
            "<Run: data=<RunData: metrics={'key-0': 0, 'key-1': 1, 'key-2': 2}, "
            "params={}, tags={}>, info=<RunInfo: artifact_uri=None, end_time=1, "
            "experiment_id=0, "
            "lifecycle_stage='active', run_id='hi', run_name='name', run_uuid='hi', "
            "start_time=0, status=4, user_id='user-id'>>"
        )
        assert str(run1) == expected

    def test_creating_run_with_absent_info_throws_exception(self, run_data):
        run_data = run_data[0]
        with pytest.raises(MlflowException, match="run_info cannot be None") as no_info_exc:
            Run(None, run_data)
        assert "run_info cannot be None" in str(no_info_exc)

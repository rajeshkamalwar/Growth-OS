import pytest

from growth_os.execution import ExecutionStatus, validate_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING),
        (ExecutionStatus.RUNNING, ExecutionStatus.AWAITING_APPROVAL),
        (ExecutionStatus.AWAITING_APPROVAL, ExecutionStatus.APPROVED),
        (ExecutionStatus.AWAITING_APPROVAL, ExecutionStatus.REJECTED),
        (ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED),
        (ExecutionStatus.RUNNING, ExecutionStatus.FAILED),
        (ExecutionStatus.QUEUED, ExecutionStatus.CANCELLED),
    ],
)
def test_valid_execution_transitions(current: ExecutionStatus, target: ExecutionStatus) -> None:
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ExecutionStatus.SUCCEEDED, ExecutionStatus.RUNNING),
        (ExecutionStatus.FAILED, ExecutionStatus.QUEUED),
        (ExecutionStatus.REJECTED, ExecutionStatus.RUNNING),
        (ExecutionStatus.CANCELLED, ExecutionStatus.QUEUED),
        (ExecutionStatus.QUEUED, ExecutionStatus.SUCCEEDED),
    ],
)
def test_invalid_execution_transitions(current: ExecutionStatus, target: ExecutionStatus) -> None:
    with pytest.raises(ValueError, match="Invalid execution transition"):
        validate_transition(current, target)

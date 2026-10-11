"""Agent-recognized score plan to a native MSCZ in one MCP call."""
from pathlib import Path
from uuid import uuid4

from .adapter import MuseScoreAdapter
from .seed import create_seed_score
from .extension import execute_extension_plan, file_identity


def build_agent_score(specification, steps, output_path, executable=''):
    output = Path(output_path).resolve()
    if output.suffix.lower() != '.mscz':
        return {'status':'error', 'error':'output_path must end in .mscz'}
    if not isinstance(steps, list) or not steps:
        return {'status':'error', 'error':'steps must be a nonempty Agent notation plan'}
    internal = output.parent/'.scorebridge'/('build-'+uuid4().hex)/output.name
    adapter = MuseScoreAdapter(executable=executable or None)
    created = create_seed_score(specification, str(internal), adapter=adapter)
    if created.get('status') != 'pass':
        return created
    plan = {'target':created['target'], 'steps':created['instrument_steps'] + steps}
    result = execute_extension_plan(plan, str(internal), str(output), adapter)
    if result.get('status') == 'executed':
        return {**result, 'status':'pass', 'target':file_identity(output),
                'parts':created['parts'], 'delivery_format':'mscz'}
    return result

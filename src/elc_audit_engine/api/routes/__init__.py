"""API blueprints。"""

from .agent_bridge import bp as agent_bridge_bp
from .appeal import bp as appeal_bp
from .attachments import bp as attachments_bp
from .bridge import bp as bridge_bp
from .clients import bp as clients_bp
from .cycle_chunks import bp as cycle_chunks_bp
from .cycles import bp as cycles_bp
from .emr_packaging import bp as emr_packaging_bp
from .his_integration import bp as his_bp
from .misc import bp as misc_bp
from .monthly import bp as monthly_bp
from .printing import bp as printing_bp
from .rules import bp as rules_bp
from .sampling import bp as sampling_bp
from .soap_recording import bp as soap_recording_bp
from .soap_review import bp as soap_review_bp
from .soap_review_queue import bp as soap_review_queue_bp
from .vault import bp as vault_bp

ALL_BLUEPRINTS = (
    misc_bp,
    sampling_bp,
    appeal_bp,
    attachments_bp,
    printing_bp,
    monthly_bp,
    rules_bp,
    his_bp,
    vault_bp,
    bridge_bp,
    emr_packaging_bp,
    soap_review_bp,
    agent_bridge_bp,
    soap_recording_bp,
    soap_review_queue_bp,
    cycles_bp,
    cycle_chunks_bp,
    clients_bp,
)

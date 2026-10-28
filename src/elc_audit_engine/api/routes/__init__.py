"""API blueprints。"""

from .appeal import bp as appeal_bp
from .attachments import bp as attachments_bp
from .misc import bp as misc_bp
from .monthly import bp as monthly_bp
from .printing import bp as printing_bp
from .rules import bp as rules_bp
from .sampling import bp as sampling_bp

ALL_BLUEPRINTS = (misc_bp, sampling_bp, appeal_bp, attachments_bp, printing_bp, monthly_bp, rules_bp)

import logging
import os
import sys
from .config import LOG_LEVEL, LOG_TO_CONSOLE, LOG_TO_FILE, LOG_FILE_PATH, LOG_FORMAT, LOG_DATE_FORMAT, CAPTURE_EXTERNAL_LOGS
 
def setup_logging(name: str = __name__) -> logging.Logger:
    """Setup logging configuration for a module.
    
    Args:
        name: The name of the module requesting the logger (usually __name__).
        
    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

    logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)

    # Console handler
    if LOG_TO_CONSOLE:
        sys.stdout.reconfigure(encoding='utf-8')
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler
    if LOG_TO_FILE:
        log_dir = os.path.dirname(LOG_FILE_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # External library logs
    if CAPTURE_EXTERNAL_LOGS:
        external_libs = ['langchain', 'google', 'groq', 'httpx', 'urllib3']
        for lib in external_libs:
            lib_logger = logging.getLogger(lib)
            lib_logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
            lib_logger.handlers.clear()
            
            if LOG_TO_CONSOLE:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
                console_handler.setFormatter(formatter)
                lib_logger.addHandler(console_handler)
            
            if LOG_TO_FILE:
                file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
                file_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
                file_handler.setFormatter(formatter)
                lib_logger.addHandler(file_handler)
            
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
    
    return logger
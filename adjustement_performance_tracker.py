# adjustement_performance_tracker.py
import time
from typing import Dict, Any
from datetime import datetime

class PerformanceTracker:
    """Track performance metrics"""
    
    def __init__(self):
        self.stats = {
            "total_requests": 0,
            "total_processing_time": 0,
            "average_processing_time": 0
        }
    
    def start_tracking(self):
        """Start a new performance tracking session"""
        return PerformanceSession()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current performance statistics"""
        return {
            **self.stats,
            "last_updated": datetime.now().isoformat()
        }

class PerformanceSession:
    """Individual performance tracking session"""
    
    def __init__(self):
        self.start_time = time.time()
        self.checkpoints = {"start": self.start_time}
        self.last_checkpoint = self.start_time
    
    def add_checkpoint(self, name: str):
        """Add a performance checkpoint"""
        current_time = time.time()
        self.checkpoints[name] = current_time
        self.last_checkpoint = current_time
    
    def get_total_time_ms(self) -> float:
        """Get total processing time in milliseconds"""
        return (time.time() - self.start_time) * 1000

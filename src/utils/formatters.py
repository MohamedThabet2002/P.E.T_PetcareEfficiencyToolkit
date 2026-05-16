"""
Formatters module for the PET Application.
Provides utility functions for formatting data for display in the UI.
"""

def format_age(months):
    """Converts a month count into a human-readable 'X years Y months' string.
    
    Args:
        months (int or float): Age in months.
        
    Returns:
        str: Formatted age string (e.g., "2 years 3 months") or empty string if invalid.
    """
    if months is None or not isinstance(months, (int, float)) or months < 0:
        return ""
    y, m = divmod(int(months), 12)
    parts = []
    if y > 0: parts.append(f"{y} year{'s' if y > 1 else ''}")
    if m > 0: parts.append(f"{m} month{'s' if m > 1 else ''}")
    return " ".join(parts) if parts else "0 months"
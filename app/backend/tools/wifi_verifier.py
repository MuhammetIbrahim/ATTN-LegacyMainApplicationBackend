# app/backend/tools/wifi_verifier.py

from ..models.db_models import Attendance

import ipaddress

def verify_wifi(attendance: Attendance, ip_address: str) -> bool:
    """
    Sağlanan IP adresinin, yoklama oturumunda kayıtlı olan IP adresiyle
    aynı ağda olup olmadığını kontrol eder.

    Args:
        attendance (Attendance): Karşılaştırma yapılacak yoklama oturumu nesnesi.
        ip_address (str): İstek yapan kullanıcının IP adresi.

    Returns:
        bool: IP adresleri aynı ağda ise True, aksi takdirde False.
    """
    if not attendance.ip_address or not ip_address:
        return False
    
    # Exact match (fastest check)
    if attendance.ip_address == ip_address:
        return True
    
    try:
        session_ip = ipaddress.ip_address(attendance.ip_address)
        student_ip = ipaddress.ip_address(ip_address)
        
        # If both are IPv6, check if they're in the same /64 subnet
        if isinstance(session_ip, ipaddress.IPv6Address) and isinstance(student_ip, ipaddress.IPv6Address):
            session_network = ipaddress.IPv6Network(f"{session_ip}/64", strict=False)
            return student_ip in session_network
        
        # If both are IPv4, check if they're in the same /24 subnet (Class C)
        elif isinstance(session_ip, ipaddress.IPv4Address) and isinstance(student_ip, ipaddress.IPv4Address):
            session_network = ipaddress.IPv4Network(f"{session_ip}/24", strict=False)
            return student_ip in session_network
        
        # If IP versions don't match, they're different networks
        return False
        
    except ValueError:
        # If IP parsing fails, fall back to exact string comparison
        return attendance.ip_address == ip_address

"""Service registry for decoupled component lookup.

Provides a central registry where components can register themselves and
other components can look them up by interface/type. This decouples UI
layout from service discovery, preventing breakage when widgets are moved.

Example:
    # Automatic registration via mixin
    class MyWidget(QWidget, AutoRegisterServiceMixin):
        SERVICE_TYPE = MyWidget  # Register as this type
        
    # Lookup anywhere
    widget = ServiceRegistry.get(MyWidget)
"""

import logging
from typing import Dict, Type, Any, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceRegistry:
    """Central registry for application services/components.
    
    Decouples service consumers from service providers by allowing
    registration and lookup by type/interface rather than widget hierarchy.
    """
    
    _services: Dict[Type, Any] = {}
    
    @classmethod
    def register(cls, service_type: Type[T], instance: T) -> None:
        """Register a service instance for a given type.
        
        Args:
            service_type: The type/interface to register under
            instance: The service instance
        """
        cls._services[service_type] = instance
        logger.debug(f"[SERVICE_REGISTRY] Registered {service_type.__name__}")
    
    @classmethod
    def get(cls, service_type: Type[T]) -> Optional[T]:
        """Get a registered service by type.
        
        Args:
            service_type: The type/interface to look up
            
        Returns:
            The registered instance, or None if not found
        """
        instance = cls._services.get(service_type)
        if instance is None:
            logger.warning(f"[SERVICE_REGISTRY] No service registered for {service_type.__name__}")
            logger.info(f"[SERVICE_REGISTRY] Available services: {list(cls._services.keys())}")
        return instance
    
    @classmethod
    def unregister(cls, service_type: Type) -> None:
        """Unregister a service.
        
        Args:
            service_type: The type to unregister
        """
        if service_type in cls._services:
            del cls._services[service_type]
            logger.debug(f"[SERVICE_REGISTRY] Unregistered {service_type.__name__}")
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered services. Useful for testing."""
        cls._services.clear()
        logger.debug("[SERVICE_REGISTRY] Cleared all services")


class AutoRegisterServiceMixin:
    """Mixin for widgets that auto-register with ServiceRegistry.
    
    Widgets inherit from this mixin to automatically register themselves
    when created and unregister when destroyed. By default, concrete
    classes register using their own class type (type(self)).
    
    Example:
        class MyWidget(QWidget, AutoRegisterServiceMixin):
            # Auto-registers as MyWidget - no SERVICE_TYPE needed!
            pass
            
    To customize the registration type (e.g., register as an interface):
        class MyWidget(QWidget, AutoRegisterServiceMixin):
            SERVICE_TYPE = IMyInterface  # Register under interface type
    
    To disable auto-registration (for abstract base classes):
        class AbstractWidget(QWidget, AutoRegisterServiceMixin):
            SERVICE_TYPE = None  # Won't auto-register
    """
    
    SERVICE_TYPE: Optional[Type] = ...
    """The type to register as. 
    
    - If ... (Ellipsis, default): Uses type(self) - concrete class auto-registers
    - If a Type: Registers as that specific type (useful for interfaces)
    - If None: Disables auto-registration (useful for abstract base classes)
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register_with_service_registry()
    
    def _register_with_service_registry(self) -> None:
        """Register this widget with the service registry."""
        service_type = self.SERVICE_TYPE
        widget_type = type(self).__name__
        logger.info(f"[AUTO_REGISTER] {widget_type}.SERVICE_TYPE = {service_type}")
        if service_type is None:
            # Explicitly disabled - don't register
            logger.info(f"[AUTO_REGISTER] {widget_type} - registration disabled (SERVICE_TYPE=None)")
            return
        if service_type is ...:
            # Default: use concrete class type
            service_type = type(self)
            logger.info(f"[AUTO_REGISTER] {widget_type} - using type(self) = {service_type.__name__}")
        ServiceRegistry.register(service_type, self)
    
    def closeEvent(self, event):
        """Unregister when widget is closed."""
        service_type = self.SERVICE_TYPE
        if service_type is None:
            # Wasn't registered
            pass
        elif service_type is ...:
            # Default: use concrete class type
            ServiceRegistry.unregister(type(self))
        else:
            ServiceRegistry.unregister(service_type)
        super().closeEvent(event)

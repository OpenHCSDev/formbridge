"""Shared utilities for field styling indicators (* and _)."""


def get_field_indicators(state, field_id, param_name):
    """Returns (has_star, has_underline) for a field."""
    path = f'{field_id}.{param_name}' if field_id else param_name
    return (path in state.dirty_fields, path in state.signature_diff_fields)


def update_reset_button_styling(button, state, field_id, field_name):
    """Apply * and _ styling to a reset button.
    
    Args:
        button: QPushButton to style
        state: ObjectState instance
        field_id: Manager's field_id
        field_name: Name of the field (e.g., 'enabled')
    """
    has_star, has_underline = get_field_indicators(state, field_id, field_name)
    
    # Update text with * prefix
    text = "Reset"
    if has_star:
        text = "*" + text
    button.setText(text)
    
    # Apply underline via font (doesn't affect stylesheet)
    font = button.font()
    font.setUnderline(has_underline)
    button.setFont(font)
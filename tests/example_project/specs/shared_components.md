- # Shared Components {{status: ready}}
    Reusable UI components and utility functions.
    
    - ## Button component {{status: done}}
        Standardized button with variants.
        
        - ### Primary button {{status: done}}
            Main action button with brand color.
            
            {{code_ref: `tests/example_project/src/components.py#L1-L25`}}
            {{verification: pytest tests/example_project/tests/test_components.py::test_primary_button -q}}
            
            - behavior: High-emphasis action trigger.
            - constraints: Only one primary action per screen.
        
        - ### Secondary button {{status: done}}
            Alternative action button.
            
            {{code_ref: `tests/example_project/src/components.py#L27-L50`}}
            {{verification: pytest tests/example_project/tests/test_components.py::test_secondary_button -q}}
            
            - behavior: Medium-emphasis action trigger.
            - constraints: Can appear multiple times.
        
        - ### Danger button {{status: done}}
            Destructive action button.
            
            {{code_ref: `tests/example_project/src/components.py#L52-L75`}}
            {{verification: pytest tests/example_project/tests/test_components.py::test_danger_button -q}}
            
            - behavior: Delete, remove, or irreversible actions.
            - constraints: Requires confirmation dialog.
    
    - ## Input component {{status: in-progress}}
        Form input with validation support.
        
        - ### Text input {{status: in-progress}}
            Single-line text entry.
            
            {{code_ref: `tests/example_project/src/components.py#L77-L105`}}
            
            - behavior: Character counter, validation, error display.
            - constraints: Max 2000 characters for text fields.
        
        - ### Textarea input {{status: draft}}
            Multi-line text entry.
            
            - behavior: Auto-resize, character counter.
            - constraints: Max 10000 characters.
    
    - ## Modal component {{status: ready}}
        Overlay dialog for focused interactions.
        
        - ### Confirm dialog {{status: ready}}
            Binary choice with OK/Cancel.
            
            {{code_ref: `tests/example_project/src/components.py#L107-L135`}}
            {{verification: pytest tests/example_project/tests/test_components.py::test_confirm_dialog -q}}
            
            - behavior: Focus trap, escape to cancel, enter to confirm.
            - constraints: Must describe action consequences.
        
        - ### Form dialog {{status: draft}}
            Modal containing a form.
            
            - behavior: Validates before close, submit on enter.
            - constraints: Scrollable if content overflows.
    
    - ## Toast notifications {{status: draft}}
        Non-blocking user feedback.
        
        - ### Success toast {{status: draft}}
            Positive action confirmation.
            
            - behavior: Auto-dismiss after 3 seconds.
            - constraints: Max 3 toasts visible at once.
        
        - ### Error toast {{status: draft}}
            Operation failure notification.
            
            - behavior: Persists until dismissed.
            - constraints: Click to view details.
        
        - ### Warning toast {{status: draft}}
            Attention-required notification.
            
            - behavior: Auto-dismiss after 5 seconds.
            - constraints: Less prominent than error.

    - ## Design Tokens
        Shared styling values.
        
        - Colors:
            - Primary: `#0066FF`
            - Success: `#00C853`
            - Warning: `#FFB300`
            - Danger: `#FF1744`
        
        - Spacing:
            - xs: 4px
            - sm: 8px
            - md: 16px
            - lg: 24px
            - xl: 32px
        
        - Border radius:
            - sm: 4px
            - md: 8px
            - lg: 12px
            - full: 9999px (pills)

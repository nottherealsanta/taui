- # Shared Components {{status: ready}}
    Reusable UI components and utility functions.
    
    - ## Button component {{status: done}}
        Standardized button with variants.
        
        - ### Primary button {{status: done}}
            Main action button with brand color.
            
            - {{code_ref: `tests/example_project/src/components.py#L1-L25`}}
            - {{verification: pytest tests/example_project/tests/test_components.py::test_primary_button -q}}
        
        - ### Secondary button {{status: done}}
            Alternative action button.
            
            - {{code_ref: `tests/example_project/src/components.py#L27-L50`}}
            - {{verification: pytest tests/example_project/tests/test_components.py::test_secondary_button -q}}
        
        - ### Danger button {{status: done}}
            Destructive action button.
            
            - {{code_ref: `tests/example_project/src/components.py#L52-L75`}}
            - {{verification: pytest tests/example_project/tests/test_components.py::test_danger_button -q}}
    
    - ## Input component {{status: in-progress}}
        Form input with validation support.
        
        - ### Text input {{status: in-progress}}
            Single-line text entry.
            
            - {{code_ref: `tests/example_project/src/components.py#L77-L105`}}
        
        - ### Textarea input {{status: draft}}
            Multi-line text entry.
    
    - ## Modal component {{status: ready}}
        Overlay dialog for focused interactions.
        
        - ### Confirm dialog {{status: ready}}
            Binary choice with OK/Cancel.
            
            - {{code_ref: `tests/example_project/src/components.py#L107-L135`}}
            - {{verification: pytest tests/example_project/tests/test_components.py::test_confirm_dialog -q}}
        
        - ### Form dialog {{status: draft}}
            Modal containing a form.
    
    - ## Toast notifications {{status: draft}}
        Non-blocking user feedback.
        
        - ### Success toast {{status: draft}}
            Positive action confirmation.
        
        - ### Error toast {{status: draft}}
            Operation failure notification.
        
        - ### Warning toast {{status: draft}}
            Attention-required notification.

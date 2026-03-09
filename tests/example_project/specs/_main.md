- Example Project 
    - A comprehensive demonstration of the Taui spec tree standards.
    
    - This project showcases all spec features including statuses, metadata, code references,
    verification evidence, dependencies, and cross-file composition.
    
    - # Core Features
        - [[task_board.md]]
        - [[auth_system.md]]
        - [[database_layer.md]]
    
    - # API Layer
        The REST API exposes all functionality to clients.
        
        - [[api_endpoints/_main.md]]
    
    - # Cross-Cutting Concerns
        Features that span multiple domains.
        
        - [[user_management.md]]
        - [[shared_components.md]]
    
    - # Deep Nesting Example
        Demonstrates heading levels L0 through L4.
        
        - ## Level 2 Feature {{status: draft}}
            A feature at heading level 2 (L2).
            
            - ### Level 3 Sub-feature {{status: draft}}
                A sub-feature at heading level 3 (L3).
                
                - #### Level 4 Implementation {{status: draft}}
                    Implementation details at heading level 4 (L4).
                    
                    - behavior: Demonstrates deep nesting capabilities.
                    - constraints: Maximum practical depth is L4-L5.

    - # Content Patterns
        Examples of different node content patterns.
        
        - ## Multi-paragraph Intent {{status: draft}}
            First paragraph of intent description.
            
            Second paragraph continues the intent.
            This is still part of the same node's content.
            
            Third paragraph with `inline code`, **bold text**, and _italic text_.
            
        - ## Metadata Patterns {{status: draft}}
            {{status: draft}}
            {{depends_on: [Task Board](task_board.md#task-board)}}
            
            This node demonstrates metadata as content lines.
            
        - ## Collapsed Node {{status: ready}} {{collapsed: true}}
            This node's children are collapsed by default.
            
            - ### Hidden Child {{status: draft}}
                This child won't be visible when collapsed.

    - # Reference Examples
        Demonstrates different link types.
        
        This is a [reference link to Task Board](task_board.md#task-board).
        The [[task_board.md]] link above is a composition link.

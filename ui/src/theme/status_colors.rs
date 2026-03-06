#[derive(Clone, Copy, Debug)]
pub struct StatusColors {
    pub error: u32,
    pub warning: u32,
    pub info: u32,
    pub success: u32,
    pub spec_draft: u32,
    pub spec_ready: u32,
    pub spec_in_progress: u32,
    pub spec_done: u32,
    pub spec_blocked: u32,
    pub box_completed: u32,
    pub box_failed: u32,
    pub box_partial: u32,
    pub box_halted: u32,
    pub clarification_blocking: u32,
    pub clarification_non_blocking: u32,
    pub amendment_proposed: u32,
    pub amendment_accepted: u32,
    pub amendment_rejected: u32,
    pub verification_met: u32,
    pub verification_unmet: u32,
    pub verification_ambiguous: u32,
}

impl StatusColors {
    pub fn taui_dark() -> Self {
        Self {
            error: 0xff6b6b,
            warning: 0xffc857,
            info: 0x7cc7ff,
            success: 0x5bd48a,
            spec_draft: 0x9aa8ba,
            spec_ready: 0x71b8ff,
            spec_in_progress: 0xffb347,
            spec_done: 0x5bd48a,
            spec_blocked: 0xff6b6b,
            box_completed: 0x5bd48a,
            box_failed: 0xff6b6b,
            box_partial: 0xffb347,
            box_halted: 0xc084fc,
            clarification_blocking: 0xff6b6b,
            clarification_non_blocking: 0xffd166,
            amendment_proposed: 0x7cc7ff,
            amendment_accepted: 0x5bd48a,
            amendment_rejected: 0xff6b6b,
            verification_met: 0x5bd48a,
            verification_unmet: 0xff6b6b,
            verification_ambiguous: 0xffd166,
        }
    }

    pub fn taui_light() -> Self {
        Self {
            error: 0xc53030,
            warning: 0xb7791f,
            info: 0x2b6cb0,
            success: 0x2f855a,
            spec_draft: 0x718096,
            spec_ready: 0x2b6cb0,
            spec_in_progress: 0xb7791f,
            spec_done: 0x2f855a,
            spec_blocked: 0xc53030,
            box_completed: 0x2f855a,
            box_failed: 0xc53030,
            box_partial: 0xb7791f,
            box_halted: 0x805ad5,
            clarification_blocking: 0xc53030,
            clarification_non_blocking: 0xb7791f,
            amendment_proposed: 0x2b6cb0,
            amendment_accepted: 0x2f855a,
            amendment_rejected: 0xc53030,
            verification_met: 0x2f855a,
            verification_unmet: 0xc53030,
            verification_ambiguous: 0xb7791f,
        }
    }
}

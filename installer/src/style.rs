use crate::preferences::Appearance;
use iced::widget::{button, container, progress_bar};
use iced::{Background, Border, Color, Theme};

#[derive(Clone, Copy)]
pub struct Colors {
    pub background: Color,
    pub surface: Color,
    pub text: Color,
    pub muted: Color,
    pub line: Color,
    pub accent: Color,
    pub accent_text: Color,
    pub error: Color,
}

pub fn colors(appearance: Appearance) -> Colors {
    match appearance {
        Appearance::Dark => Colors {
            background: Color::from_rgb8(17, 17, 17),
            surface: Color::from_rgb8(28, 28, 28),
            text: Color::from_rgb8(240, 240, 240),
            muted: Color::from_rgb8(157, 157, 157),
            line: Color::from_rgb8(56, 56, 56),
            accent: Color::from_rgb8(238, 238, 238),
            accent_text: Color::from_rgb8(20, 20, 20),
            error: Color::from_rgb8(246, 163, 155),
        },
        Appearance::Light => Colors {
            background: Color::from_rgb8(250, 250, 250),
            surface: Color::from_rgb8(239, 239, 239),
            text: Color::from_rgb8(25, 25, 25),
            muted: Color::from_rgb8(101, 101, 101),
            line: Color::from_rgb8(211, 211, 211),
            accent: Color::from_rgb8(30, 30, 30),
            accent_text: Color::WHITE,
            error: Color::from_rgb8(166, 53, 47),
        },
    }
}

pub fn theme(appearance: Appearance) -> Theme {
    let c = colors(appearance);
    Theme::custom(
        "Strahlender",
        iced::theme::Palette {
            background: c.background,
            text: c.text,
            primary: c.accent,
            success: c.accent,
            warning: c.muted,
            danger: c.error,
        },
    )
}

pub fn surface(c: Colors, highlighted: bool) -> container::Style {
    container::Style {
        background: Some(Background::Color(c.surface)),
        text_color: Some(c.text),
        border: Border {
            color: if highlighted { c.accent } else { c.line },
            width: 1.0,
            radius: 16.0.into(),
        },
        ..Default::default()
    }
}

pub fn action(c: Colors, primary: bool, status: button::Status) -> button::Style {
    let enabled = status != button::Status::Disabled;
    let hovered = matches!(status, button::Status::Hovered | button::Status::Pressed);
    let background = if primary && enabled {
        c.accent
    } else if hovered {
        c.surface
    } else {
        c.background
    };
    button::Style {
        background: Some(Background::Color(background)),
        text_color: if !enabled {
            c.muted
        } else if primary {
            c.accent_text
        } else {
            c.text
        },
        border: Border {
            color: if hovered || primary && enabled {
                c.accent
            } else {
                c.line
            },
            width: 1.0,
            radius: 10.0.into(),
        },
        ..Default::default()
    }
}

pub fn progress(c: Colors) -> progress_bar::Style {
    progress_bar::Style {
        background: Background::Color(c.line),
        bar: Background::Color(c.accent),
        border: Border {
            radius: 4.0.into(),
            ..Border::default()
        },
    }
}

//! Draws its content only in the left part of its bounds, so a second copy of a label
//! can be revealed exactly where a progress fill has reached.
use iced::advanced::layout::{self, Layout};
use iced::advanced::mouse;
use iced::advanced::renderer;
use iced::advanced::widget::{Tree, Widget};
use iced::{Element, Length, Rectangle, Size};

pub struct ClipFraction<'a, Message, Theme, Renderer> {
    content: Element<'a, Message, Theme, Renderer>,
    fraction: f32,
}

impl<'a, Message, Theme, Renderer> ClipFraction<'a, Message, Theme, Renderer> {
    pub fn new(content: impl Into<Element<'a, Message, Theme, Renderer>>, fraction: f32) -> Self {
        Self {
            content: content.into(),
            fraction: fraction.clamp(0.0, 1.0),
        }
    }
}

impl<Message, Theme, Renderer> Widget<Message, Theme, Renderer>
    for ClipFraction<'_, Message, Theme, Renderer>
where
    Renderer: iced::advanced::Renderer,
{
    fn children(&self) -> Vec<Tree> {
        vec![Tree::new(&self.content)]
    }

    fn diff(&self, tree: &mut Tree) {
        tree.diff_children(std::slice::from_ref(&self.content));
    }

    fn size(&self) -> Size<Length> {
        self.content.as_widget().size()
    }

    fn layout(
        &mut self,
        tree: &mut Tree,
        renderer: &Renderer,
        limits: &layout::Limits,
    ) -> layout::Node {
        let child = self
            .content
            .as_widget_mut()
            .layout(&mut tree.children[0], renderer, limits);
        layout::Node::with_children(child.size(), vec![child])
    }

    fn draw(
        &self,
        tree: &Tree,
        renderer: &mut Renderer,
        theme: &Theme,
        style: &renderer::Style,
        layout: Layout<'_>,
        _cursor: mouse::Cursor,
        viewport: &Rectangle,
    ) {
        let bounds = layout.bounds();
        let visible = Rectangle {
            width: bounds.width * self.fraction,
            ..bounds
        };
        if self.fraction <= 0.0 {
            return;
        }
        let Some(clip) = visible.intersection(viewport) else {
            return;
        };
        let child = layout.children().next().expect("one child");
        renderer.with_layer(clip, |renderer| {
            self.content.as_widget().draw(
                &tree.children[0],
                renderer,
                theme,
                style,
                child,
                mouse::Cursor::Unavailable,
                &clip,
            );
        });
    }
}

impl<'a, Message: 'a, Theme: 'a, Renderer: iced::advanced::Renderer + 'a>
    From<ClipFraction<'a, Message, Theme, Renderer>> for Element<'a, Message, Theme, Renderer>
{
    fn from(widget: ClipFraction<'a, Message, Theme, Renderer>) -> Self {
        Element::new(widget)
    }
}

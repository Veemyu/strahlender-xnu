use super::{InstallTarget, Installer, Message, Page, compact_name, index};
use crate::{
    drop_target,
    i18n::Label as L,
    icons::{self, Icon},
    platform::Platform,
    preferences::Appearance,
    sources::{Slot, Source},
    style,
};
use iced::widget::{
    button, column, container, mouse_area, progress_bar, row, scrollable, space, stack, text,
    toggler, tooltip,
};
use iced::{Center, Element, Fill, Size, Task, window};

// Shared width accommodates the longest German/English picker label plus padding.
const FILE_ACTION_WIDTH: f32 = 112.0;

impl Installer {
    pub(super) fn preferred_size(&self) -> Size {
        Size::new(
            crate::window_layout::WIDTH,
            if self.details {
                crate::window_layout::LOG_HEIGHT
            } else {
                crate::window_layout::HEIGHT
            },
        )
    }

    pub(super) fn fit_window(&self) -> Task<Message> {
        let size = self.preferred_size();
        #[cfg(target_os = "macos")]
        return window::latest()
            .and_then(move |id| {
                window::run(id, move |window| crate::window_layout::fit(window, size))
            })
            .map(|_| Message::LayoutApplied);
        #[cfg(not(target_os = "macos"))]
        window::latest().and_then(move |id| crate::window_layout::resize(id, size))
    }

    pub fn view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let mut header = row![
            text("strahlender").size(15).color(c.muted),
            space().width(Fill),
            self.icon_action(
                if self.appearance == Appearance::Dark {
                    Icon::Sun
                } else {
                    Icon::Moon
                },
                if self.appearance == Appearance::Dark {
                    L::UseLight
                } else {
                    L::UseDark
                },
                Message::ToggleTheme,
            ),
            self.icon_action(Icon::Github, L::OpenRepository, Message::OpenRepository),
        ]
        .align_y(Center)
        .spacing(8);
        if let Some(release) = &self.available_update {
            let mut action = button(
                text(if self.updating {
                    self.language.t(L::UpdateDownloading).to_owned()
                } else {
                    format!("{} {}", self.language.t(L::UpdateShort), release.version)
                })
                .size(11),
            )
            .padding([6, 9])
            .style(move |_, status| style::action(c, false, status));
            if !self.updating && self.backend_status != super::BackendStatus::Running {
                action = action.on_press(Message::ShowUpdateDetails);
            }
            header = header.push(action);
        }
        let body = match self.page {
            Page::Target => self.target_view(),
            Page::Keys | Page::Game | Page::Update => self.input_view(),
            Page::ModsFolder => self.mods_folder_view(),
            Page::Mods => self.mods_view(),
            Page::Review => self.review_view(),
            Page::Setup => self.setup_view(),
            Page::Progress => self.progress_view(),
            Page::Finished => self.finished_view(),
        };
        let mut top = column![header].spacing(6);
        if self.demo {
            top = top.push(
                text(if self.simulated_platform {
                    format!("{} · {}", self.host.label(), self.language.t(L::DemoMode))
                } else {
                    self.language.t(L::DemoMode).to_owned()
                })
                .size(11)
                .color(c.muted),
            );
        }
        let layout = column![
            container(top).padding(iced::Padding {
                top: 16.0,
                right: 24.0,
                bottom: 12.0,
                left: 24.0
            }),
            scrollable(
                container(body)
                    .padding(iced::Padding {
                        top: 4.0,
                        right: 24.0,
                        bottom: 8.0,
                        left: 24.0
                    })
                    .width(Fill)
            )
            .id("main-content")
            .height(Fill),
            container(self.status_footer())
                .padding([12, 24])
                .width(Fill),
        ];
        let base: Element<'_, Message> = container(layout)
            .width(Fill)
            .height(crate::window_layout::HEIGHT)
            .style(move |_| container::Style {
                background: Some(c.background.into()),
                text_color: Some(c.text),
                ..Default::default()
            })
            .into();
        let base = if self.details {
            let log = if self.log.is_empty() {
                self.language.t(L::LogEmpty).to_owned()
            } else {
                self.log.join("\n")
            };
            let log_height = crate::window_layout::LOG_HEIGHT - crate::window_layout::HEIGHT - 8.0;
            container(
                column![
                    base,
                    container(
                        scrollable(text(log).size(11).font(iced::Font::MONOSPACE))
                            .id("session-log")
                            .anchor_bottom()
                            .height(Fill),
                    )
                    .padding(12)
                    .width(Fill)
                    .height(log_height)
                    .style(move |_| style::surface(c, false)),
                ]
                .spacing(8),
            )
            .width(Fill)
            .height(Fill)
            .style(move |_| container::Style {
                background: Some(c.background.into()),
                text_color: Some(c.text),
                ..Default::default()
            })
            .into()
        } else {
            base
        };
        if let Some(notice) = &self.notice {
            let backdrop = mouse_area(
                container(space().width(Fill).height(Fill))
                    .width(Fill)
                    .height(Fill)
                    .style(move |_| container::Style {
                        background: Some(iced::Background::Color(iced::Color::from_rgba8(
                            0, 0, 0, 0.27,
                        ))),
                        ..Default::default()
                    }),
            )
            .on_press(Message::DismissNotice);
            let mut dialog = column![
                text(self.language.t(if self.update_confirmation {
                    L::UpdateAvailable
                } else {
                    L::ErrorTitle
                }))
                .size(18),
                text(notice).size(13).color(if self.update_confirmation {
                    c.text
                } else {
                    c.error
                }),
            ]
            .spacing(12);
            if self.page == super::Page::Progress {
                dialog = dialog.push(
                    text(self.language.t(L::ErrorDetailsHint))
                        .size(12)
                        .color(c.muted),
                );
            }
            let mut actions = row![].spacing(8).align_y(Center);
            if self.update_confirmation {
                actions = actions.push(
                    button(text(self.language.t(L::UpdateInstaller)).size(12))
                        .padding([8, 12])
                        .on_press(Message::UpdateInstaller)
                        .style(move |_, status| style::action(c, true, status)),
                );
            }
            if self.page == super::Page::Progress {
                actions = actions.push(
                    button(text(self.language.t(L::ShowErrorDetails)).size(12))
                        .padding([8, 12])
                        .on_press(Message::ShowNoticeDetails)
                        .style(move |_, status| style::action(c, false, status)),
                );
            }
            actions = actions.push(
                button(text(self.language.t(L::DismissError)).size(12))
                    .padding([8, 12])
                    .on_press(Message::DismissNotice)
                    .style(move |_, status| style::action(c, true, status)),
            );
            let card = container(column![dialog, actions].spacing(18))
                .width(360)
                .padding(20)
                .style(move |_| {
                    let mut surface = style::surface(c, false);
                    surface.border.radius = 20.0.into();
                    surface
                });
            let centered = container(card)
                .width(Fill)
                .height(Fill)
                .center_x(Fill)
                .center_y(Fill);
            stack![base, backdrop, centered]
                .width(Fill)
                .height(Fill)
                .into()
        } else {
            base
        }
    }

    fn title<'a>(&self, title: &'a str, subtitle: &'a str) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        column![text(title).size(23), text(subtitle).size(13).color(c.muted)]
            .spacing(8)
            .into()
    }

    fn icon_action(&self, icon: Icon, label: L, message: Message) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        tooltip(
            button(icons::view(icon, 18.0, c.text))
                .padding(8)
                .on_press(message)
                .style(move |_, status| style::action(c, false, status)),
            text(self.language.t(label)).size(12),
            tooltip::Position::Bottom,
        )
        .into()
    }

    fn target_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let mut choices = row![].spacing(10);
        for target in self
            .targets()
            .into_iter()
            .filter(|target| *target != InstallTarget::Android)
        {
            let selected = self.target == target;
            let color = if selected { c.accent_text } else { c.text };
            let mut symbols = row![].spacing(4).align_y(Center);
            if target == InstallTarget::Ios {
                symbols = symbols
                    .push(icons::view_for_host(Icon::Tablet, 26.0, color, self.host))
                    .push(icons::view_for_host(Icon::Phone, 22.0, color, self.host));
            } else {
                let icon = if target == InstallTarget::Mac {
                    Icon::Laptop
                } else {
                    Icon::Desktop
                };
                symbols = symbols.push(icons::view_for_host(icon, 26.0, color, self.host));
            }
            choices = choices.push(
                button(
                    container(
                        column![
                            container(symbols).height(26).center_y(26).center_x(Fill),
                            text(target.label()).size(14),
                        ]
                        .spacing(6)
                        .align_x(Center),
                    )
                    .width(Fill)
                    .center_x(Fill),
                )
                .padding([10, 8])
                .width(Fill)
                .on_press(Message::SelectTarget(target))
                .style(move |_, status| style::action(c, selected, status)),
            );
        }
        let android = container(
            row![
                icons::view(Icon::GenericPhone, 18.0, c.muted),
                text("Android").size(13).color(c.muted),
                space().width(Fill),
                text(self.language.t(L::ComingLater))
                    .size(11)
                    .color(c.muted),
            ]
            .spacing(8)
            .align_y(Center),
        )
        .padding([10, 14])
        .width(Fill)
        .style(move |_| style::surface(c, false));
        let hint = if self.host != Platform::Mac
            && matches!(self.target, InstallTarget::Mac | InstallTarget::Ios)
        {
            L::TargetAppleHostHint
        } else if self.target == InstallTarget::Ios {
            L::TargetMobileHint
        } else if self.target == InstallTarget::Mac {
            L::TargetMacHint
        } else {
            L::TargetDesktopHint
        };
        column![
            self.title(
                self.language.t(L::TargetTitle),
                self.language.t(L::TargetHint)
            ),
            column![choices, android].spacing(10),
            text(self.language.t(hint)).size(13).color(c.muted),
        ]
        .spacing(12)
        .into()
    }

    fn input_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let (title, hint) = match self.page {
            Page::Keys => (L::KeysTitle, L::KeysStepHint),
            Page::Game => (L::GameTitle, L::GameHint),
            _ => (L::UpdateTitle, L::UpdateHint),
        };
        let area = match self.page {
            Page::Keys => self.keys_view(),
            Page::Game => self.drop_zone(Slot::Base),
            _ => self.drop_zone(Slot::Update),
        };
        let mut body = column![
            self.title(self.language.t(title), self.language.t(hint)),
            area
        ]
        .spacing(14);
        let slot = match self.page {
            Page::Keys => Slot::Keys,
            Page::Game => Slot::Base,
            _ => Slot::Update,
        };
        if self.saved_input_missing[super::index(slot)] {
            body = body.push(
                text(self.language.t(L::SavedInputMissing))
                    .size(12)
                    .color(c.error),
            );
        }
        if self.demo
            && self
                .source(match self.page {
                    Page::Keys => Slot::Keys,
                    Page::Game => Slot::Base,
                    _ => Slot::Update,
                })
                .is_none()
        {
            body = body.push(self.text_action(self.language.t(L::UseExample), Message::DemoInput));
        }
        body.into()
    }

    fn drop_zone(&self, slot: Slot) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let source = self.source(slot);
        let pending = self.pending[index(slot)].is_some();
        let highlighted = self.hovered == Some(slot) && self.drag_active;
        let (information, actions): (Element<'_, Message>, Element<'_, Message>) =
            if let Some(source) = source {
                let mut information = column![
                    text(compact_name(&source.name())).size(16),
                    text(&source.description).size(12).color(c.muted),
                ]
                .spacing(8)
                .width(Fill);
                if slot == Slot::Base {
                    information = information.push(
                        text(format!(
                            "{} · {}",
                            self.language.t(L::Region),
                            self.language.t(L::RegionPending)
                        ))
                        .size(11)
                        .color(c.muted),
                    );
                }
                (
                    information.into(),
                    self.text_action(self.language.t(L::Remove), Message::Remove(slot)),
                )
            } else {
                (
                    column![
                        text(
                            self.language
                                .t(if pending { L::Inspecting } else { L::Drop })
                        )
                        .size(18),
                        text(self.language.t(L::Formats)).size(12).color(c.muted),
                    ]
                    .spacing(8)
                    .width(Fill)
                    .into(),
                    column![
                        self.file_action(
                            self.language.t(L::File),
                            Some(Message::Browse(slot, false)),
                            false
                        ),
                        self.file_action(
                            self.language.t(L::Folder),
                            Some(Message::Browse(slot, true)),
                            false
                        ),
                    ]
                    .spacing(8)
                    .align_x(iced::Right)
                    .into(),
                )
            };
        let body = row![
            information,
            container(actions)
                .width(FILE_ACTION_WIDTH)
                .align_x(iced::Right)
        ]
        .spacing(16)
        .align_y(Center);
        mouse_area(
            container(body)
                .id(drop_target::id(slot))
                .padding(16)
                .width(Fill)
                .style(move |_| style::surface(c, highlighted)),
        )
        .on_enter(Message::Hover(Some(slot)))
        .on_exit(Message::Hover(None))
        .into()
    }

    fn keys_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let pending = self.pending[index(Slot::Keys)].is_some();
        let source = self.keys.as_ref();
        let information = column![
            text(if pending {
                self.language.t(L::Inspecting).into()
            } else {
                source
                    .map(Source::name)
                    .unwrap_or_else(|| "prod.keys".into())
            })
            .size(16),
            text(
                source
                    .map(|s| s.description.as_str())
                    .unwrap_or_else(|| self.language.t(L::KeysHint))
            )
            .size(12)
            .color(c.muted),
        ]
        .spacing(8)
        .width(Fill);
        let mut actions = column![
            self.file_action(
                self.language
                    .t(if source.is_some() { L::Change } else { L::File }),
                Some(Message::Browse(Slot::Keys, false)),
                false,
            )
        ]
        .spacing(8)
        .align_x(iced::Right);
        if source.is_none() {
            actions = actions.push(self.file_action(
                self.language.t(L::SearchKeys),
                (!pending).then_some(Message::FindKeys),
                false,
            ));
        } else {
            actions = actions
                .push(self.text_action(self.language.t(L::Remove), Message::Remove(Slot::Keys)));
        }
        let mut body = column![
            row![
                information,
                container(actions)
                    .width(FILE_ACTION_WIDTH)
                    .align_x(iced::Right)
            ]
            .spacing(16)
            .align_y(Center)
        ]
        .spacing(12);
        if let Some(hint) = &self.key_hint {
            body = body.push(text(hint).size(12).color(c.muted));
        }
        let highlighted = self.hovered == Some(Slot::Keys) && self.drag_active;
        mouse_area(
            container(body)
                .id(drop_target::id(Slot::Keys))
                .padding(16)
                .width(Fill)
                .style(move |_| style::surface(c, highlighted)),
        )
        .on_enter(Message::Hover(Some(Slot::Keys)))
        .on_exit(Message::Hover(None))
        .into()
    }

    fn mods_folder_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let folder = self
            .chosen_mod_folder
            .as_ref()
            .or(self.mods_folder.as_ref())
            .map(|path| compact_name(&path.display().to_string()))
            .unwrap_or_else(|| self.language.t(L::ModsFolderUnavailable).into());
        let folder_card = container(
            column![
                row![
                    text(self.language.t(L::ModsFolder))
                        .size(12)
                        .color(c.muted)
                        .width(Fill),
                    self.text_action(self.language.t(L::OpenModsFolder), Message::OpenModsFolder),
                    self.text_action(
                        self.language.t(L::ChooseModFolder),
                        Message::ChooseModFolder
                    ),
                ]
                .spacing(16)
                .align_y(Center),
                text(folder).size(11).color(c.muted),
            ]
            .spacing(8),
        )
        .padding(12)
        .width(Fill)
        .style(move |_| style::surface(c, false));
        let mut body = column![
            self.title(self.language.t(L::ModsTitle), self.language.t(L::ModsHint)),
            folder_card,
            text(self.language.t(L::RomFSNoBuild))
                .size(12)
                .color(c.muted),
        ]
        .spacing(14);
        if self.target == InstallTarget::Ios {
            body = body.push(
                text(self.language.t(L::ModsDeviceHint))
                    .size(11)
                    .color(c.muted),
            );
        }
        body.into()
    }

    fn mods_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let vanilla = self.mod_choice(self.language.t(L::UnmodifiedGame), None, None);
        let mut choices = column![vanilla].spacing(6);
        for item in &self.mods {
            let tag = if item.has_exefs {
                if self.apple_ips_target() && item.ips_buildable() {
                    L::ExeFSBuildReadyTag
                } else {
                    L::ExeFSBuildNeeded
                }
            } else {
                L::RomFSOnly
            };
            choices = choices.push(self.mod_choice(
                &item.name,
                Some(&item.name),
                Some(self.language.t(tag)),
            ));
        }
        let list: Element<'_, Message> = if self.mods.len() > 3 {
            scrollable(choices).height(156).into()
        } else {
            choices.into()
        };
        let selected = self
            .selected_mod
            .as_ref()
            .and_then(|name| self.mods.iter().find(|item| &item.name == name));
        let mut body = column![
            self.title(
                self.language.t(L::ModsChooseTitle),
                self.language.t(L::ModsChooseHint)
            ),
            row![
                self.text_action(self.language.t(L::OpenModsFolder), Message::OpenModsFolder),
                self.text_action(
                    self.language.t(L::ChooseModFolder),
                    Message::ChooseModFolder
                ),
                self.text_action(self.language.t(L::RefreshMods), Message::RefreshMods),
            ]
            .spacing(18),
            list,
        ]
        .spacing(12);
        if self.mods_scanning {
            body = body.push(text(self.language.t(L::Inspecting)).size(12).color(c.muted));
        } else if self.mods.is_empty() {
            body = body.push(text(self.language.t(L::NoMods)).size(12).color(c.muted));
        }
        if let Some(item) = selected {
            if item.has_exefs {
                body = body.push(
                    text(
                        self.language
                            .t(if self.apple_ips_target() && item.ips_buildable() {
                                L::ExeFSBuildReady
                            } else if item.ips_buildable() {
                                L::ExeFSWarning
                            } else {
                                L::ExeFSUnsupported
                            }),
                    )
                    .size(12)
                    .color(c.muted),
                );
            }
        }
        if self.demo && self.mods.is_empty() {
            body = body.push(self.text_action(self.language.t(L::UseExample), Message::DemoMod));
        }
        if selected.is_none_or(|item| !item.has_exefs) {
            body = body.push(
                text(self.language.t(L::ModsPreviewHint))
                    .size(11)
                    .color(c.muted),
            );
        }
        body.into()
    }

    fn mod_choice<'a>(
        &self,
        label: &'a str,
        name: Option<&'a str>,
        tag: Option<&'a str>,
    ) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        let selected = self.selected_mod.as_deref() == name;
        let mut content = row![text(compact_name(label)).size(13).width(Fill)].align_y(Center);
        if let Some(tag) = tag {
            content = content.push(text(tag).size(10).color(if selected {
                c.accent_text
            } else {
                c.muted
            }));
        }
        button(content)
            .padding([8, 12])
            .width(Fill)
            .on_press(Message::SelectMod(name.map(str::to_owned)))
            .style(move |_, status| style::action(c, selected, status))
            .into()
    }

    fn review_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let summary = column![
            self.summary(
                self.language.t(L::Base),
                self.base.as_ref().map(Source::name).unwrap_or_default()
            ),
            self.summary(
                self.language.t(L::Region),
                self.language.t(L::RegionPending).into()
            ),
            self.summary(
                self.language.t(L::Update),
                self.update
                    .as_ref()
                    .map(Source::name)
                    .unwrap_or_else(|| self.language.t(L::NoUpdate).into())
            ),
            self.summary(
                self.language.t(L::Keys),
                self.keys.as_ref().map(Source::name).unwrap_or_default()
            ),
            if self.target == InstallTarget::Linux {
                space().height(0).into()
            } else {
                self.summary(
                    self.language.t(L::Computer),
                    format!(
                        "{} · {}",
                        self.host.label(),
                        if self.simulated_platform {
                            self.language.t(L::Simulation)
                        } else {
                            std::env::consts::ARCH
                        }
                    ),
                )
            },
            self.summary(self.language.t(L::Target), self.target.label().into()),
        ]
        .spacing(4);
        let summary = if let Some(name) = &self.selected_mod {
            if self
                .mods
                .iter()
                .any(|item| &item.name == name && item.has_exefs && item.ips_buildable())
            {
                summary.push(self.summary(self.language.t(L::ModAppResult), name.clone()))
            } else {
                summary.push(self.summary(self.language.t(L::Mods), name.clone()))
            }
        } else {
            summary
        };
        let summary = if self.target == InstallTarget::Linux {
            summary.push(
                column![
                    toggler(!self.portable_cpu)
                        .label(self.language.t(L::OptimizeCpu))
                        .text_size(14)
                        .on_toggle(Message::OptimizeCpu),
                    text(self.language.t(if self.portable_cpu {
                        L::PortableCpuHint
                    } else {
                        L::OptimizeCpuHint
                    }))
                    .size(12)
                    .color(c.muted),
                ]
                .spacing(4),
            )
        } else {
            summary
        };
        column![
            self.title(
                self.language.t(L::ReviewTitle),
                self.language.t(L::ReviewHint)
            ),
            container(summary)
                .padding(16)
                .width(Fill)
                .style(move |_| style::surface(c, false)),
        ]
        .spacing(14)
        .into()
    }

    fn setup_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        if let Some(plan) = &self.requirements
            && !plan.ready()
        {
            return column![
                self.title(
                    self.language.t(L::DependenciesTitle),
                    self.language.t(L::DependenciesHint)
                ),
                scrollable(text(plan.description()).size(12)).height(130),
            ]
            .spacing(12)
            .into();
        }
        column![
            self.title(
                self.language.t(L::SetupTitle),
                self.language.t(L::SetupHint)
            ),
            text(self.language.t(
                if self.host != Platform::Mac
                    && matches!(self.target, InstallTarget::Mac | InstallTarget::Ios)
                {
                    L::SetupAppleHost
                } else if self.target == InstallTarget::Mac {
                    L::SetupMac
                } else if self.target == InstallTarget::Ios {
                    L::SetupMobile
                } else {
                    L::SetupDesktop
                }
            ))
            .size(13)
            .color(c.muted),
            text(self.language.t(if self.demo {
                L::PreviewHint
            } else if self.backend_supported() {
                L::BackendHint
            } else {
                L::BackendUnavailable
            }))
            .size(12)
            .color(c.muted),
        ]
        .spacing(18)
        .into()
    }

    fn progress_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        if !self.demo && self.backend_status != super::BackendStatus::Idle {
            let stage = self.build_progress.active;
            let state = self.build_progress.stages[stage.index()];
            let status = self.build_labels()[stage.index()];
            let detail = match self.backend_status {
                super::BackendStatus::Running if stage == crate::progress::Stage::Requirements => {
                    L::CheckingRequirements
                }
                super::BackendStatus::Running => status,
                super::BackendStatus::Passed => L::BuildPassed,
                super::BackendStatus::Failed => L::BuildFailed,
                super::BackendStatus::Stopped => L::BuildStopped,
                super::BackendStatus::Idle => unreachable!(),
            };
            let counter = match stage {
                crate::progress::Stage::Compile if state.total > 0 => format!(
                    "{} / {} {}",
                    state.completed,
                    state.total,
                    self.language.t(L::FilesCompiled)
                ),
                crate::progress::Stage::Generate if state.total > 0 => format!(
                    "{} / {} {}",
                    state.completed,
                    state.total,
                    self.language.t(L::ModulesGenerated)
                ),
                _ => self
                    .language
                    .t(match self.backend_status {
                        super::BackendStatus::Running => L::Running,
                        super::BackendStatus::Passed => L::Done,
                        super::BackendStatus::Failed => L::NeedsAttention,
                        super::BackendStatus::Stopped => L::BuildStopped,
                        super::BackendStatus::Idle => unreachable!(),
                    })
                    .to_owned(),
            };
            return column![
                self.title(self.language.t(L::ProgressTitle), self.language.t(detail)),
                container(
                    column![
                        row![
                            text(self.language.t(status)).size(16).width(Fill),
                            text(counter).size(12).color(c.muted),
                        ]
                        .spacing(12)
                        .align_y(Center),
                        progress_bar(
                            0.0..=1.0,
                            (self.motion.value - stage.index() as f32).clamp(0.0, 1.0)
                        )
                        .girth(5)
                        .style(move |_| style::progress(c)),
                    ]
                    .spacing(16)
                )
                .padding(16)
                .width(Fill)
                .style(move |_| style::surface(c, false)),
                if stage == crate::progress::Stage::Requirements {
                    column![].into()
                } else {
                    self.progress_context(stage.index())
                },
            ]
            .spacing(14)
            .into();
        }
        let stages = self.build_stages();
        let stage = stages[((self.tick / 10) as usize).min(stages.len() - 1)].index();
        let counter = if stage == crate::progress::Stage::Compile.index() {
            format!(
                "{} / 2369 {}",
                ((self.tick % 10) as u64 * 2369 / 10),
                self.language.t(L::FilesCompiled)
            )
        } else if stage == crate::progress::Stage::Generate.index() {
            format!(
                "{} / 4 {}",
                ((self.tick % 10) as u64 * 4 / 10),
                self.language.t(L::ModulesGenerated)
            )
        } else {
            format!(
                "{} · {} %",
                self.language.t(L::Running),
                (self.tick % 10) * 10
            )
        };
        column![
            self.title(
                self.language.t(L::ProgressTitle),
                self.language.t(L::Simulated)
            ),
            container(
                column![
                    row![
                        text(self.language.t(self.build_labels()[stage]))
                            .size(16)
                            .width(Fill),
                        text(counter).size(12).color(c.muted),
                    ]
                    .spacing(12)
                    .align_y(Center),
                    progress_bar(
                        0.0..=1.0,
                        (self.motion.value - stage as f32).clamp(0.0, 1.0)
                    )
                    .girth(5)
                    .style(move |_| style::progress(c)),
                ]
                .spacing(16)
            )
            .padding(16)
            .width(Fill)
            .style(move |_| style::surface(c, false)),
            self.progress_context(stage),
        ]
        .spacing(14)
        .into()
    }

    fn progress_context(&self, stage: usize) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let labels = self.build_labels();
        let mut context = column![].spacing(10);
        let stages = self.build_stages();
        let previous = stages.iter().rev().find(|item| {
            item.index() < stage
                && (self.demo
                    || self.capture.is_some()
                    || self.build_progress.stages[item.index()].done)
        });
        if let Some(previous) = previous {
            context = context.push(
                row![
                    text(self.language.t(L::CompletedStage))
                        .size(12)
                        .color(c.muted)
                        .width(105),
                    text(self.language.t(labels[previous.index()])).size(12),
                ]
                .spacing(8),
            );
        }
        if let Some(next) = stages.iter().find(|item| item.index() > stage) {
            context = context.push(
                row![
                    text(self.language.t(L::NextStage))
                        .size(12)
                        .color(c.muted)
                        .width(105),
                    text(self.language.t(labels[next.index()])).size(12),
                ]
                .spacing(8),
            );
        }
        context.into()
    }

    fn navigation(&self) -> Element<'_, Message> {
        let mut actions = row![].spacing(12).align_y(Center);
        if self.page != Page::Target && self.page != Page::Progress {
            actions = actions.push(self.text_action(self.language.t(L::Back), Message::Back));
        }
        actions = actions.push(space().width(Fill));
        if self.page == Page::Setup && self.requirements.as_ref().is_some_and(|p| !p.ready()) {
            actions =
                actions.push(self.text_action(self.language.t(L::CheckAgain), Message::Preview));
        }
        let (label, message, primary) = match self.page {
            Page::Progress if self.backend_status == super::BackendStatus::Running => (
                if self.demo { L::Stop } else { L::CancelBuild },
                Some(Message::Back),
                false,
            ),
            Page::Progress if self.backend_status != super::BackendStatus::Idle && !self.demo => {
                (L::ReturnToSetup, Some(Message::Back), false)
            }
            Page::Progress => (L::Stop, Some(Message::Back), false),
            Page::Setup if self.demo => (L::StartPreview, Some(Message::Preview), true),
            Page::Setup if self.updating => (L::UpdateDownloading, None, false),
            Page::Setup if self.requirements_busy => (L::CheckingRequirements, None, false),
            Page::Setup if self.requirements.is_some() => (
                L::InstallDependencies,
                Some(Message::InstallRequirements),
                true,
            ),
            Page::Setup if self.backend_supported() => {
                (L::StartBuild, Some(Message::Preview), true)
            }
            Page::Setup => (L::BackendUnavailable, None, false),
            Page::Update if self.update.is_none() => {
                (L::SkipUpdate, self.ready().then_some(Message::Review), true)
            }
            _ => (L::Continue, self.ready().then_some(Message::Review), true),
        };
        let c = style::colors(self.appearance);
        if matches!(self.page, Page::ModsFolder | Page::Mods) {
            actions =
                actions.push(self.text_action(self.language.t(L::SkipMods), Message::SkipMods));
        }
        actions
            .push(
                button(text(self.language.t(label)).size(14))
                    .padding([10, 20])
                    .on_press_maybe(message)
                    .style(move |_, status| style::action(c, primary, status)),
            )
            .into()
    }

    fn status_footer(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        let active = self.active_step();
        let labels = self.step_labels();
        let caption = if self.page == Page::Finished {
            self.language.t(L::Done).to_owned()
        } else {
            format!(
                "{} {} {} {} · {}",
                self.language.t(L::Step),
                active + 1,
                self.language.t(L::Of),
                labels.len(),
                self.language.t(labels[active])
            )
        };
        let mut segments = row![].spacing(5);
        let build_stages = self.build_stages();
        let build_start = labels.len() - build_stages.len();
        for i in 0..labels.len() {
            let value = if self.page == Page::Progress && i >= build_start {
                let stage = build_stages[i - build_start].index();
                if self.demo || self.backend_status == super::BackendStatus::Idle {
                    (self.motion.value - stage as f32).clamp(0.0, 1.0)
                } else if self.build_progress.stages[stage].done {
                    1.0
                } else if stage == self.build_progress.active.index() {
                    (self.motion.value - stage as f32).clamp(0.0, 1.0)
                } else {
                    0.0
                }
            } else if i < active || self.page == Page::Finished {
                1.0
            } else {
                0.0
            };
            let current = i == active && self.page != Page::Finished;
            segments = segments.push(
                container(
                    progress_bar(0.0..=1.0, value)
                        .girth(6)
                        .style(move |_| style::progress(c)),
                )
                .padding(3)
                .width(iced::Length::FillPortion(
                    if i >= build_start
                        && build_stages[i - build_start] == crate::progress::Stage::Compile
                    {
                        3
                    } else if i >= build_start
                        && build_stages[i - build_start] == crate::progress::Stage::Generate
                    {
                        2
                    } else {
                        1
                    },
                ))
                .style(move |_| container::Style {
                    border: iced::Border {
                        color: if current { c.accent } else { c.background },
                        width: 1.0,
                        radius: 6.0.into(),
                    },
                    ..Default::default()
                }),
            );
        }
        let mut controls = row![self.text_action(
            self.language.t(if self.details {
                L::HideDetails
            } else {
                L::Details
            }),
            Message::ToggleDetails
        )]
        .align_y(Center);
        if self.details {
            controls = controls
                .push(space().width(Fill))
                .push(self.text_action(self.language.t(L::CopyLog), Message::CopyLog));
        }
        let mut footer = column![].spacing(10);
        if self.page != Page::Finished {
            footer = footer.push(self.navigation());
        }
        footer = footer
            .push(text(caption).size(11).color(c.muted))
            .push(segments)
            .push(controls);
        footer.into()
    }

    fn finished_view(&self) -> Element<'_, Message> {
        let c = style::colors(self.appearance);
        column![
            text(self.language.t(L::FinishedTitle)).size(25),
            text(self.language.t(L::FinishedHint))
                .size(14)
                .color(c.muted),
            self.action(self.language.t(L::ToSelection), Some(Message::Back), true),
        ]
        .spacing(24)
        .into()
    }

    fn summary<'a>(&self, label: &'a str, value: String) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        row![
            text(label).size(12).color(c.muted).width(82),
            text(compact_name(&value)).size(13).width(Fill)
        ]
        .spacing(12)
        .into()
    }

    fn file_action<'a>(
        &self,
        label: &'a str,
        message: Option<Message>,
        primary: bool,
    ) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        button(text(label).size(12).width(Fill).align_x(Center))
            .width(FILE_ACTION_WIDTH)
            .padding([8, 12])
            .on_press_maybe(message)
            .style(move |_, status| style::action(c, primary, status))
            .into()
    }

    fn action<'a>(
        &self,
        label: &'a str,
        message: Option<Message>,
        primary: bool,
    ) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        button(text(label).size(12))
            .padding([8, 12])
            .on_press_maybe(message)
            .style(move |_, status| style::action(c, primary, status))
            .into()
    }

    fn text_action<'a>(&self, label: &'a str, message: Message) -> Element<'a, Message> {
        let c = style::colors(self.appearance);
        button(text(label).size(12))
            .padding([3, 0])
            .on_press(message)
            .style(move |_, status| iced::widget::button::Style {
                text_color: if status == iced::widget::button::Status::Hovered {
                    c.text
                } else {
                    c.muted
                },
                ..Default::default()
            })
            .into()
    }
}

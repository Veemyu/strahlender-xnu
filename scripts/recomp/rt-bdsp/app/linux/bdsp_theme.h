// Dark/light theme for the native Qt hosts: Fusion style with an explicit palette, so menu bars, menus and dialogs match on every desktop.
// BDSP_QT_THEME=dark|light overrides; otherwise the system colour scheme decides and an unknown scheme falls back to dark.
#pragma once
#include <QApplication>
#include <QGuiApplication>
#include <QPalette>
#include <QStyle>
#include <QStyleFactory>
#include <QStyleHints>

namespace bdsp {
inline QPalette darkPalette() {
    QPalette p;
    const QColor window(32, 33, 36), base(24, 25, 27), text(232, 234, 237), accent(66, 133, 244);
    p.setColor(QPalette::Window, window);
    p.setColor(QPalette::WindowText, text);
    p.setColor(QPalette::Base, base);
    p.setColor(QPalette::AlternateBase, window);
    p.setColor(QPalette::ToolTipBase, window);
    p.setColor(QPalette::ToolTipText, text);
    p.setColor(QPalette::Text, text);
    p.setColor(QPalette::Button, QColor(45, 46, 50));
    p.setColor(QPalette::ButtonText, text);
    p.setColor(QPalette::BrightText, Qt::white);
    p.setColor(QPalette::Link, accent);
    p.setColor(QPalette::Highlight, accent);
    p.setColor(QPalette::HighlightedText, Qt::white);
    p.setColor(QPalette::PlaceholderText, QColor(154, 160, 166));
    for (QPalette::ColorRole r : {QPalette::WindowText, QPalette::Text, QPalette::ButtonText})
        p.setColor(QPalette::Disabled, r, QColor(112, 116, 122));
    return p;
}

inline bool wantDark() {
    const QString forced = qEnvironmentVariable("BDSP_QT_THEME").toLower();
    if (forced == QLatin1String("dark")) return true;
    if (forced == QLatin1String("light")) return false;
    return QGuiApplication::styleHints()->colorScheme() != Qt::ColorScheme::Light;
}

inline void applyTheme() {
    if (wantDark()) QApplication::setPalette(darkPalette());
    else QApplication::setPalette(QApplication::style()->standardPalette());
}

inline void installTheme() {
    QApplication::setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
    applyTheme();
    QObject::connect(QGuiApplication::styleHints(), &QStyleHints::colorSchemeChanged, qApp, [] { applyTheme(); });
}
} // namespace bdsp

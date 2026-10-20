// Icon preferences shared by both native Qt hosts. All images are generated in work/.
#pragma once
#include <QActionGroup>
#include <QApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>
#include <QMenuBar>
#include <QSettings>
#include <QWidget>

namespace bdsp {
inline QString iconsDirectory() {
    const QString specified = qEnvironmentVariable("BDSP_ICON_DIR");
    const QString base = QCoreApplication::applicationDirPath();
    for (const QString &path : {specified, base + "/icons/linux", base + "/../icons/linux"}) {
        if (!path.isEmpty() && QFile::exists(path + "/icons.json")) return path;
    }
    return {};
}

inline QString recommendedIcon(const QJsonArray &variants, const QString &fallback) {
    for (QString locale : QLocale::system().uiLanguages()) {
        locale.replace('_', '-');
        for (const QJsonValue &v : variants)
            if (v.toObject()["id"].toString().compare(locale, Qt::CaseInsensitive) == 0) return v.toObject()["id"].toString();
        if (locale.startsWith("zh-")) {
            const bool traditional = locale.contains("Hant") || locale.endsWith("-TW") || locale.endsWith("-HK") || locale.endsWith("-MO");
            const QString script = traditional ? "zh-Hant" : "zh-Hans";
            for (const QJsonValue &v : variants) if (v.toObject()["id"].toString() == script) return script;
        }
        if (fallback.section('-', 0, 0) == locale.section('-', 0, 0)) return fallback;
        for (const QJsonValue &v : variants)
            if (v.toObject()["id"].toString().section('-', 0, 0) == locale.section('-', 0, 0)) return v.toObject()["id"].toString();
    }
    return fallback;
}

inline void installIconMenu(QMenuBar *bar, QWidget *window) {
    const QString directory = iconsDirectory();
    QFile file(directory + "/icons.json");
    if (!file.open(QIODevice::ReadOnly)) return;
    const QJsonObject metadata = QJsonDocument::fromJson(file.readAll()).object();
    const QJsonArray variants = metadata["variants"].toArray();
    const QString fallback = metadata["default"].toString();
    const QString recommended = recommendedIcon(variants, fallback);
    const bool german = QLocale::system().language() == QLocale::German;
    QSettings settings("dev.local", "xnubdsp");
    QString selection = settings.value("bdsp_app_icon", "default").toString();
    bool found = selection == "default";
    for (const QJsonValue &v : variants) if (v.toObject()["id"].toString() == selection) found = true;
    if (!found) { selection = "default"; settings.setValue("bdsp_app_icon", selection); }
    QMenu *menu = bar->addMenu(german ? "App-Symbol" : "App icon");
    QActionGroup *group = new QActionGroup(menu);
    group->setExclusive(true);
    const auto apply = [window, directory, variants, fallback](const QString &choice) {
        for (const QJsonValue &v : variants) {
            const QJsonObject item = v.toObject();
            if (item["id"].toString() != (choice == "default" ? fallback : choice)) continue;
            const QString image = item["image"].toString();
            if (QFileInfo(image).fileName() != image) return;
            QIcon icon(directory + "/" + image);
            qApp->setWindowIcon(icon);
            window->setWindowIcon(icon);
            return;
        }
    };
    const auto add = [&](const QString &label, const QString &id) {
        QAction *action = menu->addAction(label);
        action->setCheckable(true);
        action->setChecked(id == selection);
        group->addAction(action);
        QObject::connect(action, &QAction::triggered, window, [apply, id] {
            QSettings preferences("dev.local", "xnubdsp");
            preferences.setValue("bdsp_app_icon", id);
            apply(id);
        });
    };
    QString defaultLabel = german ? "Standard (Englisch)" : "Default (English)";
    if (!fallback.startsWith("en-")) for (const QJsonValue &v : variants) {
        if (v.toObject()["id"].toString() == fallback)
            defaultLabel = (german ? "Standard (" : "Default (") + v.toObject()["label"].toString() + ")";
    }
    add(defaultLabel, "default");
    for (const QJsonValue &v : variants) {
        QJsonObject item = v.toObject();
        QString label = item["label"].toString();
        if (item["id"].toString() == recommended) label += german ? " (empfohlen)" : " (recommended)";
        add(label, item["id"].toString());
    }
    QGuiApplication::setDesktopFileName("dev.local.xnubdsp");
    apply(selection);
}
} // namespace bdsp

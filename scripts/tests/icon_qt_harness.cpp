// Synthetic integration test of the actual Qt icon menu; generated files belong under work/.
#include "../recomp/rt-bdsp/app/linux/bdsp_icons.h"
#include <QImage>
#include <QJsonDocument>
#include <cassert>

int main(int argc, char **argv) {
    assert(argc == 2);
    const QString root = QFileInfo(QString::fromLocal8Bit(argv[1])).absoluteFilePath();
    QDir().mkpath(root + "/prefs");
    QSettings::setPath(QSettings::NativeFormat, QSettings::UserScope, root + "/prefs");
    qputenv("BDSP_ICON_DIR", root.toUtf8());
    QApplication app(argc, argv);
    QJsonArray variants;
    int color = 0;
    for (const QString &id : {QString("en-US"), QString("de"), QString("ja")}) {
        QImage picture(32, 32, QImage::Format_RGB32);
        picture.fill(color++ == 0 ? Qt::red : Qt::blue);
        assert(picture.save(root + "/" + id + ".png"));
        variants.append(QJsonObject{{"id", id}, {"label", id}, {"image", id + ".png"}});
    }
    const auto write = [&] {
        QFile file(root + "/icons.json");
        assert(file.open(QIODevice::WriteOnly));
        file.write(QJsonDocument(QJsonObject{{"schema", 1}, {"default", "en-US"}, {"variants", variants}}).toJson());
    };
    write();
    QSettings settings("dev.local", "xnubdsp");
    settings.clear();
    QWidget first;
    QMenuBar bar;
    bdsp::installIconMenu(&bar, &first);
    assert(!first.windowIcon().isNull());
    const qint64 original = first.windowIcon().cacheKey();
    const auto actions = bar.actions().first()->menu()->actions();
    assert(actions.size() == 4 && actions.first()->isChecked());
    actions.last()->trigger();
    assert(settings.value("bdsp_app_icon").toString() == "ja");
    assert(first.windowIcon().cacheKey() != original);
    QWidget second;
    QMenuBar secondBar;
    bdsp::installIconMenu(&secondBar, &second);
    assert(secondBar.actions().first()->menu()->actions().last()->isChecked());
    variants.removeLast();
    write();
    QWidget third;
    QMenuBar thirdBar;
    bdsp::installIconMenu(&thirdBar, &third);
    assert(settings.value("bdsp_app_icon").toString() == "default");
    assert(thirdBar.actions().first()->menu()->actions().first()->isChecked());
    return 0;
}

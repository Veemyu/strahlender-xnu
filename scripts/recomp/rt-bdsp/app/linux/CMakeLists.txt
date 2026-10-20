# Qt-Hülle (Menüleiste, eingebetteter Vulkan-Canvas) für BDSP unter Linux. Nur Linux; der Mac-Pfad (app_ui.m) nutzt dies nicht.
# Bau: scripts/recomp/rt-bdsp/app/linux/build_qt.sh (prüft Qt6/CMake und nennt bei Fehlen den Installationsbefehl, siehe deps.txt).
cmake_minimum_required(VERSION 3.16)
project(bdsp_qt_host LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "bdsp_qt_host ist nur für Linux (X11/Xwayland-Einbettung)")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(bdsp_qt_host bdsp_qt_host.cpp bdsp_l10n.h)
target_link_libraries(bdsp_qt_host PRIVATE Qt6::Widgets)
target_compile_options(bdsp_qt_host PRIVATE -Wall -Wextra)
# Übersetzungen (lproj/<Ort>.lproj/Localizable.strings): neben die Binärdatei kopieren, Rückfall ist der Quellordner
target_compile_definitions(bdsp_qt_host PRIVATE BDSP_LPROJ_DIR="${CMAKE_CURRENT_SOURCE_DIR}/lproj")
add_custom_command(TARGET bdsp_qt_host POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_CURRENT_SOURCE_DIR}/lproj $<TARGET_FILE_DIR:bdsp_qt_host>/lproj)

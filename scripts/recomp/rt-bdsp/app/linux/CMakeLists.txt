# Qt shell (menu bar, embedded Vulkan canvas) for BDSP on Linux. Linux only; the Mac path (app_ui.m) does not use this.
# Build: scripts/recomp/rt-bdsp/app/linux/build_qt.sh (checks Qt6/CMake and prints the install command if missing, see deps.txt).
cmake_minimum_required(VERSION 3.16)
project(bdsp_qt_host LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "bdsp_qt_host is for Linux only (X11/Xwayland embedding)")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(bdsp_qt_host bdsp_qt_host.cpp bdsp_l10n.h bdsp_icons.h bdsp_theme.h)
target_link_libraries(bdsp_qt_host PRIVATE Qt6::Widgets)
target_compile_options(bdsp_qt_host PRIVATE -Wall -Wextra)
# Translations (lproj/<locale>.lproj/Localizable.strings): copied next to the binary, the fallback is the source folder
target_compile_definitions(bdsp_qt_host PRIVATE BDSP_LPROJ_DIR="${CMAKE_CURRENT_SOURCE_DIR}/lproj")
add_custom_command(TARGET bdsp_qt_host POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_CURRENT_SOURCE_DIR}/lproj $<TARGET_FILE_DIR:bdsp_qt_host>/lproj)

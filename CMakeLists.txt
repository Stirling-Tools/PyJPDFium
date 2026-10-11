cmake_minimum_required(VERSION 3.20)
project(pyjpdfium LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The extension links the one shared JPDFium core; it never compiles its own copy of the domain.
set(JPDFIUM_NATIVE_DIR "" CACHE PATH "Staged JPDFium natives (libjpdfium plus its runtime closure)")
set(JPDFIUM_INCLUDE_DIR "" CACHE PATH "Directory containing jpdfium_api.h")
option(PYJPDFIUM_BUNDLE_NATIVES "Copy the staged natives into the wheel under pyjpdfium/_libs" OFF)

if(NOT JPDFIUM_NATIVE_DIR)
    message(FATAL_ERROR "Set JPDFIUM_NATIVE_DIR to a staged JPDFium native directory")
endif()
if(NOT JPDFIUM_INCLUDE_DIR)
    set(JPDFIUM_INCLUDE_DIR "${JPDFIUM_NATIVE_DIR}/include")
endif()
if(NOT EXISTS "${JPDFIUM_INCLUDE_DIR}/jpdfium_api.h")
    message(FATAL_ERROR "jpdfium_api.h not found in ${JPDFIUM_INCLUDE_DIR}; set JPDFIUM_INCLUDE_DIR")
endif()

find_library(JPDFIUM_LIBRARY NAMES jpdfium PATHS "${JPDFIUM_NATIVE_DIR}" NO_DEFAULT_PATH REQUIRED)
message(STATUS "JPDFium core: ${JPDFIUM_LIBRARY}")

find_package(Python 3.10 COMPONENTS Interpreter Development.Module REQUIRED)
execute_process(
    COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
    OUTPUT_STRIP_TRAILING_WHITESPACE
    OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)

nanobind_add_module(_native NB_STATIC src/native/pyjpdfium_native.cpp)
target_include_directories(_native PRIVATE "${JPDFIUM_INCLUDE_DIR}")
target_link_libraries(_native PRIVATE "${JPDFIUM_LIBRARY}")
if(MSVC)
    target_compile_options(_native PRIVATE /W4 /WX)
else()
    target_compile_options(_native PRIVATE -Wall -Wextra -Werror)
endif()

# Bundled wheels find the core next to the package; dev builds preload it from JPDFIUM_NATIVE_DIR.
if(APPLE)
    set_target_properties(_native PROPERTIES INSTALL_RPATH "@loader_path/_libs")
elseif(UNIX)
    set_target_properties(_native PROPERTIES INSTALL_RPATH "$ORIGIN/_libs")
endif()

install(TARGETS _native LIBRARY DESTINATION pyjpdfium)

# Optional OCR extension: built when the staged natives include libjpdfium_ocr.
set(JPDFIUM_OCR_INCLUDE_DIR "${JPDFIUM_INCLUDE_DIR}/../../ocr/include" CACHE PATH
    "Directory containing jpdfium_ocr.h")
find_library(JPDFIUM_OCR_LIBRARY NAMES jpdfium_ocr PATHS "${JPDFIUM_NATIVE_DIR}" NO_DEFAULT_PATH)
if(JPDFIUM_OCR_LIBRARY AND EXISTS "${JPDFIUM_OCR_INCLUDE_DIR}/jpdfium_ocr.h")
    message(STATUS "JPDFium OCR module: ${JPDFIUM_OCR_LIBRARY}")
    nanobind_add_module(_ocr_native NB_STATIC src/native/pyjpdfium_ocr_native.cpp)
    target_include_directories(_ocr_native PRIVATE "${JPDFIUM_INCLUDE_DIR}" "${JPDFIUM_OCR_INCLUDE_DIR}")
    target_link_libraries(_ocr_native PRIVATE "${JPDFIUM_OCR_LIBRARY}" "${JPDFIUM_LIBRARY}")
    if(MSVC)
        target_compile_options(_ocr_native PRIVATE /W4 /WX)
    else()
        target_compile_options(_ocr_native PRIVATE -Wall -Wextra -Werror)
    endif()
    if(APPLE)
        set_target_properties(_ocr_native PROPERTIES INSTALL_RPATH "@loader_path/_libs")
    elseif(UNIX)
        set_target_properties(_ocr_native PROPERTIES INSTALL_RPATH "$ORIGIN/_libs")
    endif()
    install(TARGETS _ocr_native LIBRARY DESTINATION pyjpdfium)
else()
    message(STATUS "JPDFium OCR module not staged; pyjpdfium.ocr will be unavailable")
endif()

if(PYJPDFIUM_BUNDLE_NATIVES)
    # The staged closure with its manifests and license texts (tools/build_wheel.py).
    install(DIRECTORY "${JPDFIUM_NATIVE_DIR}/" DESTINATION pyjpdfium/_libs
        FILES_MATCHING PATTERN "*.so*" PATTERN "*.dylib" PATTERN "*.dll"
        PATTERN "*.json" PATTERN "licenses/*")
endif()

#include "4DPluginAPI.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>

static std::map<PA_Unichar*, size_t> strings;
static std::map<PA_Handle, size_t> handles;
static std::map<PA_Picture, unsigned> pictures;
static bool nullEmpty;
static bool commandNoop;
static bool replacePicture;
static CUTF16String expectedText;
static const char* testName;

static void require(bool condition, const char* message)
{
    if (!condition) {
        std::fprintf(stderr, "%s: %s\n", testName, message);
        std::exit(1);
    }
}

static PA_Unistring makeString(const PA_Unichar* text)
{
    PA_Unistring result = {};
    const size_t length = text ? PA_GetUnicharsLength(const_cast<PA_Unichar*>(text)) : 0;
    if (length || !nullEmpty) {
        result.fString = new PA_Unichar[length + 1];
        if (length) std::memcpy(result.fString, text, length * sizeof(PA_Unichar));
        result.fString[length] = 0;
        PA_Unichar* buffer = result.fString;
        strings[buffer] = length;
    }
    result.fLength = static_cast<PA_long32>(length);
    return result;
}

static void checkString(PA_Unistring value, const CUTF16String& expected)
{
    require(value.fLength == expected.size(), "wrong UTF-16 code-unit count");
    if (value.fString) {
        PA_Unichar* buffer = value.fString;
        require(strings.count(buffer) == 1, "string is not live");
        require(strings.at(buffer) == expected.size(), "wrong string allocation length");
        require(value.fString[value.fLength] == 0, "missing UTF-16 terminator");
        require(CUTF16String(value.fString, value.fLength) == expected, "wrong exact string content");
    } else {
        require(expected.empty(), "null nonempty string");
    }
}

static void disposeString(PA_Unistring value)
{
    if (!value.fString) return;
    PA_Unichar* buffer = value.fString;
    require(strings.erase(buffer) == 1, "double disposal or borrowed string disposal");
    delete[] value.fString;
}

static PA_Picture makePicture(bool empty)
{
    if (empty && nullEmpty) return nullptr;
    PA_Picture result = new unsigned(0x50494354);
    pictures[result] = 1;
    return result;
}

static void checkPicture(PA_Picture value)
{
    require(value && pictures.count(value) == 1, "picture did not survive owning handoff");
    require(*static_cast<unsigned*>(value) == 0x50494354, "invalid picture payload");
}

static void disposePicture(PA_Picture value)
{
    if (!value) return;
    require(pictures.count(value) == 1, "double picture disposal");
    if (--pictures.at(value) == 0) {
        pictures.erase(value);
        delete static_cast<unsigned*>(value);
    }
}

static void clear(PA_Variable* value)
{
    require(value->fFiller == 0, "metadata cleanup is outside shim contract");
    switch (value->fType) {
        case eVK_Unistring:
            disposeString(value->uValue.fString);
            break;
        case eVK_Picture:
            disposePicture(value->uValue.fPicture);
            break;
        case eVK_ArrayUnicode: {
            PA_Handle data = value->uValue.fArray.fData;
            require(handles.count(data) == 1, "array handle is not live");
            auto elements = reinterpret_cast<PA_Unistring*>(*data);
            for (PA_long32 i = 0; i <= value->uValue.fArray.fNbElements; ++i)
                disposeString(elements[i]);
            PA_DisposeHandle(data);
            break;
        }
        case eVK_Undefined:
        case eVK_Longint:
            break;
        default:
            require(false, "unimplemented variable cleanup");
    }
    *value = {};
    value->fType = eVK_Undefined;
}

static void engine(short selector, EngineBlock* eb)
{
    switch (selector) {
        case EX_CREATE_UNISTRING:
            eb->fUniString1 = makeString(reinterpret_cast<PA_Unichar*>(eb->fHandle));
            break;
        case EX_DISPOSE_UNISTRING:
            disposeString(eb->fUniString1);
            break;
        case EX_SET_UNISTRING: {
            // Copy before freeing: the content setter is not a descriptor transfer.
            PA_Unistring copy = makeString(reinterpret_cast<PA_Unichar*>(eb->fHandle));
            disposeString(eb->fUniString1);
            eb->fUniString1 = copy;
            break;
        }
        case EX_CLEAR_VARIABLE:
            clear(static_cast<PA_Variable*>(eb->fPtr1));
            break;
        case EX_CREATE_PICTURE:
            eb->fPicture = makePicture(eb->fParam1 == 0);
            eb->fError = 0;
            break;
        case EX_DISPOSE_PICTURE:
            disposePicture(eb->fPicture);
            break;
        case EX_DUPLICATE_PICTURE:
            if (eb->fPicture) {
                checkPicture(eb->fPicture);
                PA_Picture picture = eb->fPicture;
                if (eb->fParam1 == 0) ++pictures.at(picture);
                else eb->fPicture = makePicture(false);
            }
            break;
        case EX_GET_PICTURE_DATA:
            // No representations: output ownership on success is deliberately not modeled.
            eb->fError = eER_IncompatibleTypes;
            std::memset(&eb->fUniString1, 0xa5, sizeof(eb->fUniString1));
            break;
        case EX_HANDLE_MANAGER: {
            const auto operation = eb->fParam1;
            if (operation == 1) {
                eb->fHandle = new char*;
                *eb->fHandle = new char[eb->fParam2]();
                PA_Handle handle = eb->fHandle;
                handles[handle] = eb->fParam2;
            } else {
                PA_Handle handle = eb->fHandle;
                require(handles.count(handle) == 1, "invalid handle");
                if (operation == 2) {
                    handles.erase(handle);
                    delete[] *eb->fHandle;
                    delete eb->fHandle;
                } else if (operation == 3) {
                    const size_t size = eb->fParam2;
                    char* replacement = new char[size]();
                    std::memcpy(replacement, *eb->fHandle,
                                std::min(size, handles.at(handle)));
                    delete[] *eb->fHandle;
                    *eb->fHandle = replacement;
                    handles[handle] = size;
                } else if (operation == 4) {
                    eb->fParam2 = handles.at(handle);
                } else if (operation == 5) {
                    eb->fParam3 = reinterpret_cast<sLONG_PTR>(*eb->fHandle);
                } else {
                    require(operation == 6, "unimplemented handle operation");
                }
            }
            eb->fError = 0;
            break;
        }
        case EX_CONVERT_CHARSET_TO_CHARSET: {
            require(eb->fParam2 == eVTC_UTF_8 && eb->fParam4 == eVTC_UTF_16,
                    "unexpected conversion charsets");
            CFStringRef text = CFStringCreateWithBytes(kCFAllocatorDefault,
                static_cast<UInt8*>(eb->fPtr1), eb->fParam1, kCFStringEncodingUTF8, false);
            require(text != nullptr, "invalid fixture UTF-8");
            const size_t units = CFStringGetLength(text);
            const size_t bytes = units * sizeof(PA_Unichar);
            require(bytes <= eb->fParam3, "conversion capacity is in bytes");
            if (units) CFStringGetCharacters(text, CFRangeMake(0, units),
                                             static_cast<UniChar*>(eb->fPtr2));
            CFRelease(text);
            // No terminator is counted or written; capacity remains the caller's responsibility.
            eb->fParam3 = bytes;
            eb->fError = 0;
            break;
        }
        case EX_EXECUTE_COMMAND_BY_ID: {
            auto args = static_cast<PA_Variable**>(eb->fPtr1);
            auto result = static_cast<PA_Variable*>(eb->fPtr2);
            require(result->fType == eVK_Undefined, "command result not initialized");
            if (eb->fParam1 == 678) {
                require(eb->fParam2 == 2, "READ PICTURE FILE arity");
                checkString(args[0]->uValue.fString, expectedText);
                if (!commandNoop) {
                    clear(args[1]);
                    PA_SetPictureVariable(args[1], makePicture(false));
                }
            } else if (eb->fParam1 == 1002 || eb->fParam1 == 988) {
                checkPicture(PA_GetPictureVariable(*args[0]));
                if (eb->fParam1 == 1002)
                    checkString(args[1]->uValue.fString, expectedText);
                if (replacePicture) {
                    clear(args[0]);
                    PA_SetPictureVariable(args[0], makePicture(false));
                }
            } else if (eb->fParam1 == 457) {
                checkPicture(PA_GetPictureVariable(*args[0]));
                PA_SetLongintVariable(args[1], 17);
                PA_SetLongintVariable(args[2], 23);
            } else if (eb->fParam1 == 679) {
                checkPicture(PA_GetPictureVariable(*args[0]));
                if (!commandNoop) {
                    clear(args[1]);
                    PA_SetPictureVariable(args[1], makePicture(false));
                }
            } else {
                require(false, "unexpected command");
            }
            // These five commands are procedures, not owning-result functions.
            eb->fError = commandNoop ? eER_IncompatibleTypes : eER_NoErr;
            break;
        }
        default:
            std::fprintf(stderr, "unexpected engine selector: %d\n", selector);
            require(false, "unimplemented engine boundary");
    }
}

static CUTF16String utf16(const char* utf8)
{
    CFStringRef value = CFStringCreateWithBytes(kCFAllocatorDefault,
        reinterpret_cast<const UInt8*>(utf8), std::strlen(utf8), kCFStringEncodingUTF8, false);
    require(value != nullptr, "bad fixture");
    CUTF16String result(CFStringGetLength(value), 0);
    if (!result.empty())
        CFStringGetCharacters(value, CFRangeMake(0, result.size()), &result[0]);
    CFRelease(value);
    return result;
}

static void balanced()
{
    require(strings.empty(), "leaked string allocation");
    require(handles.empty(), "leaked handle allocation");
    require(pictures.empty(), "leaked picture reference");
}

static void fileTest()
{
    for (const char* text : {"synthetic-path", "\xc3\xa9\xe6\x97\xa5", "\xf0\x9f\x98\x80", ""}) {
        expectedText = utf16(text);
        CUTF8String path(reinterpret_cast<const uint8_t*>(text));
        CPicture picture;
        picture.fromFileAtPath(&path);
        picture.fromFileAtPath(&path);
        if (!commandNoop) checkPicture(picture.getPicture());
    }
}

static void bytesTest()
{
    CPicture picture;
    const uint8_t bytes[] = {1, 2, 3};
    for (int i = 0; i < 8; ++i) {
        picture.setBytes(bytes, sizeof(bytes));
        checkPicture(picture.getPicture());
    }
}

static void copyTest()
{
    for (const char* type : {".png", "\xc3\xa9\xe6\x97\xa5", "\xf0\x9f\x98\x80", ""}) {
        PA_Picture result;
        {
            CPicture picture;
            const uint8_t bytes[] = {1};
            // Use a borrowed input with a separate creation owner.
            PA_Picture input = PA_CreatePicture(const_cast<uint8_t*>(bytes), sizeof(bytes));
            picture.setPicture(input);
            PA_DisposePicture(input);
            expectedText = utf16(type);
            result = picture.createCopy(type);
            checkPicture(picture.getPicture());
            checkPicture(result);
        }
        checkPicture(result);
        PA_DisposePicture(result);
    }
}

static void helpersTest(const std::string& which)
{
    PA_Picture handoff = nullptr;
    {
        CPicture picture;
        const uint8_t bytes[] = {1};
        PA_Picture input = PA_CreatePicture(const_cast<uint8_t*>(bytes), sizeof(bytes));
        PackagePtr params = nullptr;
        uint8_t* arguments[] = {reinterpret_cast<uint8_t*>(&input)};
        params = arguments;
        picture.fromParamAtIndex(params, 1);
        PA_DisposePicture(input);
        if (which == "gray") handoff = picture.createGrayScale();
        if (which == "thumbnail") handoff = picture.createThumbnail(17, 23);
        if (which == "size") {
            unsigned width = 0, height = 0;
            picture.getSize(&width, &height);
            require(width == 17 && height == 23, "wrong scalar picture outputs");
        }
        if (which == "return") {
            picture.setReturn(reinterpret_cast<sLONG_PTR*>(&handoff));
        }
        if (which == "param") {
            handoff = PA_CreatePicture(nullptr, 0);
            uint8_t* output[] = {reinterpret_cast<uint8_t*>(&handoff)};
            picture.toParamAtIndex(output, 1);
            picture.toParamAtIndex(output, 1);
        }
        checkPicture(picture.getPicture());
    }
    if (handoff) {
        checkPicture(handoff);
        PA_DisposePicture(handoff);
    }
}

static void arrayTest()
{
    const CUTF16String fixtures[] = {utf16("ASCII"), utf16("\xc3\xa9\xe6\x97\xa5"),
                                     utf16("\xf0\x9f\x98\x80"), utf16("")};
    PA_Variable array = PA_CreateVariable(eVK_ArrayUnicode);
    PA_ResizeArray(&array, 3);
    for (int i = 0; i < 4; ++i) {
        PA_Unistring value = PA_CreateUnistring(const_cast<PA_Unichar*>(fixtures[i].c_str()));
        PA_SetStringInArray(array, i, &value);
        checkString(PA_GetStringInArray(array, i), fixtures[i]);
    }
    PA_Unistring borrowed = PA_GetStringInArray(array, 0);
    C_TEXT copy;
    copy.setUTF16String(&borrowed);
    PA_Unistring independent = PA_CreateUnistring(const_cast<PA_Unichar*>(copy.getUTF16StringPtr()));
    PA_SetStringInArray(array, 1, &independent);
    require(PA_GetStringInArray(array, 0).fString != independent.fString,
            "independent array outputs alias");
    PA_Unistring replacement = PA_CreateUnistring(const_cast<PA_Unichar*>(fixtures[2].c_str()));
    PA_SetStringInArray(array, 0, &replacement);
    require(CUTF16String(copy.getUTF16StringPtr(), copy.getUTF16Length()) == fixtures[0],
            "borrowed scalar copy did not survive owner mutation");
    PA_Variable callback[2] = {PA_CreateVariable(eVK_Undefined),
                               PA_CreateVariable(eVK_Picture)};
    PA_Unistring callbackText = PA_CreateUnistring(
        const_cast<PA_Unichar*>(fixtures[0].c_str()));
    PA_SetStringVariable(&callback[0], &callbackText);
    require(callbackText.fString != independent.fString, "callback aliases array owner");
    expectedText = fixtures[0];
    PA_Variable result = PA_ExecuteCommandByID(678, callback, 2);
    PA_ClearVariable(&result);
    PA_ClearVariable(&callback[0]);
    PA_ClearVariable(&callback[1]);
    checkString(PA_GetStringInArray(array, 1), fixtures[0]);
    PA_ResizeArray(&array, 1);
    PA_ResizeArray(&array, 4);
    PA_Unistring empty = {};
    PA_SetStringInArray(array, 4, &empty);
    checkString(PA_GetStringInArray(array, 4), fixtures[3]);
    for (int mode = 0; mode < 4; ++mode) {
        PA_Unistring value = PA_CreateUnistring(const_cast<PA_Unichar*>(fixtures[0].c_str()));
        PA_Variable invalid = array;
        int index = 0;
        if (mode == 0) invalid.fType = eVK_Longint;
        if (mode == 1) invalid.uValue.fArray.fData = nullptr;
        if (mode == 2) index = -1;
        if (mode == 3) index = 5;
        PA_SetStringInArray(invalid, index, &value);
        checkString(value, fixtures[0]);
        PA_DisposeUnistring(&value);
    }
    PA_Unistring before = PA_GetStringInArray(array, 0);
    PA_SetStringInArray(array, 0, nullptr);
    require(PA_GetStringInArray(array, 0).fString == before.fString,
            "null descriptor should reject without replacing");
    PA_ClearVariable(&array);
    require(CUTF16String(copy.getUTF16StringPtr(), copy.getUTF16Length()) == fixtures[0],
            "copy invalidated by array clear");

    PA_Variable output = PA_CreateVariable(eVK_Undefined);
    uint8_t* arguments[] = {reinterpret_cast<uint8_t*>(&output)};
    ARRAY_TEXT wrapper;
    for (const auto& fixture : fixtures) wrapper.appendUTF16String(fixture.c_str());
    wrapper.toParamAtIndex(arguments, 1);
    ARRAY_TEXT snapshot;
    snapshot.fromParamAtIndex(arguments, 1);
    wrapper.toParamAtIndex(arguments, 1);
    for (int i = 0; i < 4; ++i) checkString(PA_GetStringInArray(output, i), fixtures[i]);
    wrapper.setSize(2);
    wrapper.toParamAtIndex(arguments, 1);
    PA_ClearVariable(&output);
    for (int i = 0; i < 4; ++i) {
        CUTF16String value;
        snapshot.copyUTF16StringAtIndex(&value, i);
        require(value == fixtures[i], "array wrapper borrowed copy did not survive clear");
    }
}

static void scalarTest()
{
    for (const char* text : {"ASCII", "\xc3\xa9\xe6\x97\xa5", "\xf0\x9f\x98\x80", ""}) {
        CUTF16String fixture = utf16(text);
        PA_Unistring source = PA_CreateUnistring(const_cast<PA_Unichar*>(fixture.c_str()));
        C_TEXT wrapper;
        uint8_t* arguments[] = {reinterpret_cast<uint8_t*>(&source)};
        wrapper.fromParamAtIndex(arguments, 1);
        PA_DisposeUnistring(&source);
        PA_Unistring destination = {};
        PA_Unistring* pointer = &destination;
        wrapper.setReturn(reinterpret_cast<sLONG_PTR*>(&pointer));
        checkString(destination, fixture);
        wrapper.toParamAtIndex(arguments, 1);
        checkString(source, fixture);
        PA_Variable argument = PA_CreateVariable(eVK_Undefined);
        PA_SetStringVariable(&argument, &source);
        PA_ClearVariable(&argument);
        checkString(destination, fixture);
        PA_DisposeUnistring(&destination);
    }
}

static void conversionTest()
{
    for (const char* text : {"ASCII", "\xc3\xa9\xe6\x97\xa5", "\xf0\x9f\x98\x80", ""}) {
        CUTF16String expected = utf16(text);
        const size_t bytes = expected.size() * sizeof(PA_Unichar);
        std::vector<PA_Unichar> output(expected.size() + 2, 0x5a5a);
        auto count = PA_ConvertCharsetToCharset(const_cast<char*>(text), std::strlen(text),
            eVTC_UTF_8, reinterpret_cast<char*>(output.data()), bytes, eVTC_UTF_16);
        require(count == bytes, "charset result must be bytes excluding terminator");
        require(CUTF16String(output.data(), expected.size()) == expected, "conversion content");
        require(output[expected.size()] == 0x5a5a && output[expected.size() + 1] == 0x5a5a,
                "conversion exceeded byte capacity or wrote a terminator");
    }
}

int main(int argc, char** argv)
{
    require(argc == 5, "usage: test case null-empty command-noop replace-picture");
    testName = argv[1];
    nullEmpty = std::string(argv[2]) == "1";
    commandNoop = std::string(argv[3]) == "1";
    replacePicture = std::string(argv[4]) == "1";
    gCall4D = engine;
    // Exercise the real dispatcher without touching a bookmark or filesystem path.
    PluginBlock parameters = {};
    sLONG_PTR ignored = 0;
    parameters.fResult = &ignored;
    PluginMain(-999, &parameters);
    std::string name(testName);
    if (name == "file") fileTest();
    else if (name == "bytes") bytesTest();
    else if (name == "copy") copyTest();
    else if (name == "array") arrayTest();
    else if (name == "scalar") scalarTest();
    else if (name == "conversion") conversionTest();
    else helpersTest(name);
    balanced();
    std::printf("PASS %s null-empty=%d noop=%d replace=%d; strings=0 handles=0 pictures=0\n",
                testName, nullEmpty, commandNoop, replacePicture);
}

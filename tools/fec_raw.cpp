// SPDX-License-Identifier: Apache-2.0
// Minimal raw-image adapter for the AOSP FEC interleaving and libfec RS encoder.
// Geometry: system/extras/libfec/include/fec/ecc.h (android-15.0.0_r1).
// This tool is not the full Android fec CLI. Only the options below are supported.
extern "C" {
#include <fec.h>
}
#include <openssl/sha.h>
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

static uint64_t number(const std::string& s) {
    size_t n = 0;
    auto result = std::stoull(s, &n);
    if (n != s.size() || s.empty() || s[0] == '-') throw std::runtime_error("invalid number");
    return result;
}
static uint64_t up(uint64_t n, uint64_t d) { return n / d + (n % d != 0); }
static void put32(unsigned char* p, uint32_t v) {
    for (int i=0;i<4;++i) p[i] = static_cast<unsigned char>(v >> (8*i));
}
static void put64(unsigned char* p, uint64_t v) {
    for (int i=0;i<8;++i) p[i] = static_cast<unsigned char>(v >> (8*i));
}
static void write_all(int fd, const void* data, size_t size) {
    auto p = static_cast<const unsigned char*>(data);
    while (size) {
        ssize_t n = write(fd, p, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) throw std::runtime_error("write failed");
        p += n; size -= static_cast<size_t>(n);
    }
}
int main(int argc, char** argv) try {
    int roots = 2;
    uint64_t data_size = 0, fec_offset = 0, expected_fec_size = 0, print_size = 0;
    bool verify = false;
    std::vector<std::string> positional;
    for (int i=1;i<argc;++i) {
        std::string a = argv[i];
        auto value = [&]() -> std::string {
            if (++i >= argc) throw std::runtime_error("missing option value");
            return argv[i];
        };
        if (a == "--encode") {}
        else if (a == "--verify") verify = true;
        else if (a == "--roots") roots = static_cast<int>(number(value()));
        else if (a == "--data-size") data_size = number(value());
        else if (a == "--fec-offset") fec_offset = number(value());
        else if (a == "--fec-size") expected_fec_size = number(value());
        else if (a == "--print-fec-size") print_size = number(value());
        else if (a.rfind("--print-fec-size=",0)==0) print_size = number(a.substr(17));
        else if (a.rfind("--roots=",0)==0) roots = static_cast<int>(number(a.substr(8)));
        else if (a.rfind("--",0)==0) throw std::runtime_error("unsupported option: " + a);
        else positional.push_back(a);
    }
    if (roots < 1 || roots >= 255) throw std::runtime_error("invalid roots");
    constexpr uint64_t block = 4096;
    uint64_t rsn = 255 - roots;
    auto parity_size = [&](uint64_t n) { return up(up(n,block),rsn)*roots*block; };
    if (print_size) {
        std::cout << parity_size(print_size) + block << '\n';
        return 0;
    }
    if (positional.size() != (verify ? 1u : 2u)) throw std::runtime_error("expected input and output (or verify input)");
    int fd = open(positional[0].c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) throw std::runtime_error("cannot open input");
    struct stat st{};
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size <= 0) throw std::runtime_error("input must be a regular raw file");
    uint64_t file_size = static_cast<uint64_t>(st.st_size);
    if (!data_size) data_size = file_size;
    if (data_size > file_size || data_size % block) throw std::runtime_error("data size must be block aligned and within input");
    uint64_t rounds = up(up(data_size,block),rsn), bytes = parity_size(data_size), codes = rounds*block;
    if (bytes > std::numeric_limits<uint32_t>::max()) throw std::runtime_error("FEC size exceeds header capacity");
    auto input = static_cast<const unsigned char*>(mmap(nullptr,file_size,PROT_READ,MAP_PRIVATE,fd,0));
    if (input == MAP_FAILED) throw std::runtime_error("mmap failed");
    std::vector<unsigned char> parity(bytes);
    const unsigned threads = 2;
    std::vector<void*> states;
    for (unsigned t=0;t<threads;++t) {
        void* rs = init_rs_char(8,0x11d,0,1,roots,0);
        if (!rs) throw std::runtime_error("init_rs_char failed");
        states.push_back(rs);
    }
    std::vector<std::thread> workers;
    for (unsigned t=0;t<threads;++t) workers.emplace_back([&,t] {
        std::array<unsigned char,255> data{};
        for (uint64_t k=codes*t/threads;k<codes*(t+1)/threads;++k) {
            for (uint64_t j=0;j<rsn;++j) {
                uint64_t offset = k + j*rounds*block;
                data[j] = offset < data_size ? input[offset] : 0;
            }
            encode_rs_char(states[t],data.data(),parity.data()+k*roots);
        }
    });
    for (auto& t : workers) t.join();
    for (auto p : states) free_rs_char(p);
    if (verify) {
        if (bytes != expected_fec_size || fec_offset > file_size || bytes > file_size-fec_offset)
            throw std::runtime_error("FEC geometry mismatch");
        if (memcmp(parity.data(),input+fec_offset,bytes)) throw std::runtime_error("FEC parity mismatch");
        std::cout << "FEC RS(255," << rsn << "): " << bytes << " parity bytes match\n";
    } else {
        struct stat outst{};
        if (stat(positional[1].c_str(),&outst)==0 && st.st_dev==outst.st_dev && st.st_ino==outst.st_ino)
            throw std::runtime_error("input and output must differ");
        int out = open(positional[1].c_str(),O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0600);
        if (out<0) throw std::runtime_error("cannot open output");
        std::array<unsigned char,4096> header{};
        put32(header.data(),0xfecfecfe); put32(header.data()+4,0); put32(header.data()+8,60);
        put32(header.data()+12,roots); put32(header.data()+16,bytes); put64(header.data()+20,data_size);
        SHA256(parity.data(),parity.size(),header.data()+28);
        memcpy(header.data()+header.size()-60,header.data(),60);
        write_all(out,parity.data(),parity.size()); write_all(out,header.data(),header.size());
        if (fsync(out) || close(out)) throw std::runtime_error("output flush failed");
    }
    munmap(const_cast<unsigned char*>(input),file_size); close(fd);
    return 0;
} catch (const std::exception& e) {
    std::cerr << "fec-raw: " << e.what() << '\n'; return 1;
}
